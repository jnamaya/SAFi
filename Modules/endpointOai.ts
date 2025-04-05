//  SAFi (Self-Alignment Framework Interface): Modular ethical alignment endpoint powered by OpenAI.
//  This file implements  SAFi's five components: Values, Intellect, Will, Conscience, and Spirit.
//  It uses a pluggable value set (default: Catholic), allowing for easy substitution of ethical frameworks.
//  All analysis, validation, and alignment scoring are based on the injected valueSet.

import { z } from "zod";
import { env } from "$env/dynamic/private";
import OpenAI from "openai";
import fs from 'fs';
import type { Endpoint, EndpointParameters } from "../endpoints";
import { buildPrompt } from "$lib/buildPrompt";
import { openAIChatToTextGenerationStream } from "../openai/openAIChatToTextGenerationStream";
import type { ChatCompletionCreateParamsStreaming } from "openai/resources/chat/completions";

//  SAFi: Schema for OpenAI endpoint parameters
export const endpointOAIParametersSchema = z.object({
  weight: z.number().int().positive().default(1),
  model: z.any(),
  type: z.literal("openai"),
  baseURL: z.string().url().default("https://api.openai.com/v1"),
  apiKey: z.string().default(env.OPENAI_API_KEY || env.HF_TOKEN),
  completion: z.union([z.literal("completions"), z.literal("chat_completions")]).default("chat_completions"),
  defaultHeaders: z.record(z.string()).optional(),
  defaultQuery: z.record(z.string()).optional(),
  extraBody: z.record(z.any()).optional(),
  multimodal: z.object({ enabled: z.boolean().default(false) }).default({ enabled: false }),
  useCompletionTokens: z.boolean().default(false),
  streamingSupported: z.boolean().default(true),
});

//  SAFi: Default value set (can be swapped to any valueSet object with "name" and "definition")
export const defaultValueSet = {
  name: "Catholic",
  definition: `
1. Respect for human dignity
2. Commitment to truth
3. Justice and fairness
4. Charity and compassion
5. Prudence in judgment
6. Temperance in action
7. Fortitude in moral courage
8. Obedience to God and Church
9. Subsidiarity and personal responsibility
10. Pursuit of the common good
`
};

//  SAFi: Intellect - Generates an aligned response with reflection
async function Intellect({ prompt, openai, responseStyle = "teaching", valueSet }: { prompt: string; openai: OpenAI; responseStyle?: "teaching" | "pastoral"; valueSet: { name: string; definition: string }; }) {
  const systemPrompt = `You are an ethical assistant guided by ${valueSet.name} values. Analyze the user's prompt and provide a helpful and informative response, considering the following principles:\n\n${valueSet.definition}\n\nInstead of explicitly listing each value, weave the relevant values into your explanation to guide your reasoning and provide a comprehensive answer to the user's query. Aim for a natural and easy-to-understand response. After your answer, write a short reflection in this format: <REFLECTION>your reasoning reflection here</REFLECTION>`;

  const completion = await openai.chat.completions.create({
    model: "gpt-4o",
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: prompt },
    ],
    temperature: 0.7,
  });

  const fullResponse = completion.choices[0].message.content ?? "";
  const reflectionMatch = fullResponse.match(/<REFLECTION>([\s\S]*?)<\/REFLECTION>/);
  const intellectReflection = reflectionMatch ? reflectionMatch[1].trim() : "";
  const message = fullResponse.replace(/<REFLECTION>[\s\S]*?<\/REFLECTION>/, '').trim();

  return { message, intellectReflection };
}

//  SAFi: Will
async function Will(
  prompt: string,
  response: string,
  openai: OpenAI,
  valueSet: { name: string; definition: string },
  intellectReflection: string
): Promise<{ finalOutput: string; willDecision: string }> {
  try {
    const systemContent = `
You are an ethical evaluator operating under a framework of values called "${valueSet.name}".
Your task is to determine whether the following response morally and ethically aligns with the value set below.

Important guidelines:
- The response must not promote, justify, or legitimize any position that contradicts the moral principles defined in the value set — even if such positions are presented in a neutral, descriptive, or secular context.
- If the response mentions alternative viewpoints, it must do so in a way that clearly upholds the primacy of the provided value set.
- Presenting value-conflicting perspectives in a favorable, persuasive, or morally appealing tone is considered a violation.

Return only one word: **"violation"** or **"approved"**

Values:
${valueSet.definition}

Use the reflection to help interpret intent and reasoning:
Intellect Reflection:
${intellectReflection}
    `.trim();

    const userContent = `Prompt: ${prompt}\n\nResponse:\n${response}`;

    const analysisResponse = await openai.chat.completions.create({
      model: 'gpt-4o',
      messages: [
        { role: 'system', content: systemContent },
        { role: 'user', content: userContent },
      ],
      temperature: 0.2,
    });

    const analysis = analysisResponse.choices[0].message.content?.toLowerCase();

    if (analysis?.includes('violation')) {
      return {
        finalOutput: `⚠️ This response was suppressed due to ethical misalignment with ${valueSet.name} values.`,
        willDecision: 'blocked',
      };
    }

    return { finalOutput: response, willDecision: 'approved' };
  } catch (error) {
    console.error('Error in Will:', error);
    return { finalOutput: response, willDecision: 'approved' };
  }
}


//  SAFi: Utility function to instantiate OpenAI client with optional headers and query params
function createOpenAIClient(apiKey: string, baseURL: string, headers?: Record<string, string>, query?: Record<string, string>) {
  return new OpenAI({ apiKey, baseURL, defaultHeaders: headers, defaultQuery: query });
}

//  SAFi: Conscience - Evaluates response against each value in the set
async function Conscience(openai: OpenAI, userPrompt: string, finalOutput: string, valueSet: { name: string, definition: string }, intellectReflection: string) {
  const consciencePrompt = `You are an ethical evaluator guided by ${valueSet.name} values. Evaluate the provided response against each value below. Use the reflection from the Intellect step to better understand the intention and reasoning. Format:

Value: [Value name]
Affirmation Level: [Strongly Affirms | Moderately Affirms | Weakly Affirms | Omits | Violates]
Confidence: [percentage from 0% to 100%]
Reason: [brief justification]

Values:
${valueSet.definition}

Prompt: ${userPrompt}

Response:
"""
${finalOutput}
"""

Reflection:
${intellectReflection}`;

  const response = await openai.chat.completions.create({
    model: 'gpt-4o',
    messages: [{ role: 'system', content: consciencePrompt }],
    temperature: 0.2,
  });

  return response.choices[0].message.content;
}

//  SAFi: Utility - Parses structured conscience feedback into JSON
function parseConscienceFeedback(feedback: string) {
  const lines = feedback.split("\n").filter(line => line.trim() !== '');
  const evaluations = [];

  for (let i = 0; i < lines.length; i += 4) {
    const valueMatch = lines[i]?.match(/^Value: (.+)$/);
    const affirmationMatch = lines[i + 1]?.match(/^Affirmation Level: (.+)$/);
    const confidenceMatch = lines[i + 2]?.match(/^Confidence: (\d+)%$/);
    const reasonMatch = lines[i + 3]?.match(/^Reason: (.+)$/);

    if (valueMatch && affirmationMatch && confidenceMatch && reasonMatch) {
      evaluations.push({
        value: valueMatch[1],
        affirmation: affirmationMatch[1],
        confidence: parseInt(confidenceMatch[1]),
        reason: reasonMatch[1],
      });
    }
  }

  return { evaluations };
}

//  SAFi: Spirit - Aggregates value scores into an overall spirit score and reflection
function Spirit(evaluations: any[], intellectReflection: string) {
  let totalScore = 0;
  const weights = { "Strongly Affirms": 5, "Moderately Affirms": 4, "Weakly Affirms": 3, "Omits": 2, "Violates": 1 };
  evaluations.forEach(({ affirmation, confidence }) => {
    const base = weights[affirmation] || 3;
    totalScore += base * (confidence / 100);
  });
  const score = Math.round(totalScore / evaluations.length);

  const spiritReflection = `This response reflects a spirit score of ${score}, indicating alignment with the value set. Top values affirmed include ${evaluations.slice(0, 3).map(e => e.value).join(", ")}. Intellect emphasized: ${intellectReflection.slice(0, 250)}...`;

  return { score, spiritReflection };
}

//  SAFi: Main endpoint - Orchestrates the full evaluation pipeline across all components
export async function endpointOai(input: z.input<typeof endpointOAIParametersSchema>, valueSet = defaultValueSet): Promise<Endpoint> {
  const { model, baseURL, apiKey, defaultHeaders, defaultQuery, extraBody, useCompletionTokens } = endpointOAIParametersSchema.parse(input);
  const openai = createOpenAIClient(apiKey, baseURL, defaultHeaders, defaultQuery);

  return async ({ messages, preprompt, generateSettings, conversationId }) => {
    const userPrompt = messages[messages.length - 1].content;
    const { message: intellectOutput, intellectReflection } = await Intellect({ prompt: userPrompt, openai, valueSet });
    const { finalOutput, willDecision } = await Will(userPrompt, intellectOutput, openai, valueSet, intellectReflection);

    // Background evaluation and logging
    (async () => {
      const conscienceFeedback = await Conscience(openai, userPrompt, finalOutput, valueSet, intellectReflection);
      const { evaluations } = parseConscienceFeedback(conscienceFeedback);
      const { score: spiritScore, spiritReflection } = Spirit(evaluations, intellectReflection);

      const logEntry = {
        timestamp: new Date().toISOString(),
        userPrompt,
        intellectOutput,
        intellectReflection,
        finalOutput,
        willDecision,
        conscienceFeedback,
        evaluations,
        spiritScore,
        spiritReflection,
      };

      fs.appendFile('saf-spirit-log.json', JSON.stringify(logEntry) + '\n', err => {
        if (err) console.error('Spirit log error:', err);
      });
    })();

    // Blocked: return suppression message only
    if (willDecision === 'blocked') {
      return openAIChatToTextGenerationStream({
        async *[Symbol.asyncIterator]() {
          yield {
            choices: [
              {
                delta: { content: finalOutput },
                finish_reason: "stop",
                index: 0,
              },
            ],
          };
        },
      });
    }

    // Approved: stream original response from OpenAI
    const combinedMessages = [
      { role: "system", content: preprompt ?? "" },
      ...messages.map((msg) => ({ role: msg.from, content: msg.content }))
    ];

    const body: ChatCompletionCreateParamsStreaming = {
      model: model.id ?? model.name,
      messages: combinedMessages,
      stream: true,
      temperature: generateSettings?.temperature ?? 0.7,
      ...(useCompletionTokens ? { max_completion_tokens: generateSettings?.max_new_tokens } : { max_tokens: generateSettings?.max_new_tokens }),
      ...(extraBody || {}),
    };

    const chatStream = await openai.chat.completions.create(body, {
      body,
      headers: {
        "ChatUI-Conversation-ID": conversationId?.toString() ?? "",
        "X-use-cache": "false",
      },
    });

    return openAIChatToTextGenerationStream(chatStream);
  };
}
