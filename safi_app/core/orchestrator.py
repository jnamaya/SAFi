"""
Defines the SAFi class, the main orchestrator for the application.
"""
from __future__ import annotations
import json
import threading
import uuid
import asyncio
import numpy as np
from datetime import datetime, timezone
from typing import List, Dict, Any, Union, Optional
from pathlib import Path
import logging
from concurrent.futures import ThreadPoolExecutor

# --- Import Provider SDKs (Needed for Sync Clients) ---
from openai import OpenAI
from google import genai

# --- Import App-Specific Core Modules ---
from collections import deque
from .feedback import build_spirit_feedback
from ..persistence import database as db
from .faculties import IntellectEngine, WillGate, ConscienceAuditor, SpiritIntegrator
from .plugins.bible_scholar_readings import handle_bible_scholar_commands
from .plugins.fiduciary_data import handle_fiduciary_commands

# --- Import Mixins ---
from .orchestrator_mixins.tts import TtsMixin
from .orchestrator_mixins.suggestions import SuggestionsMixin
from .orchestrator_mixins.tasks import BackgroundTasksMixin

# --- Import Refactored Services ---
# --- Import Refactored Services ---
from .services import LLMProvider, RAGService, MCPManager

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class SAFi(TtsMixin, SuggestionsMixin, BackgroundTasksMixin):
    """
    Orchestrates Intellect, Will, Conscience, and Spirit faculties.
    """

    def __init__(
        self,
        config,
        value_profile_or_list: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        value_set: Optional[List[Dict[str, Any]]] = None,
        intellect_model: Optional[str] = None,
        will_model: Optional[str] = None,
        conscience_model: Optional[str] = None,
        spirit_beta: Optional[float] = None
    ):
        """
        Initializes the SAFi orchestration system.
        """
        self.config = config
        self.log = logging.getLogger(self.__class__.__name__)
        
        # --- PRODUCTION FIX: ThreadPool for Background Tasks ---
        self.executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="SafiWorker")

        # --- Helper: Auto-detect Provider ---
        def detect_provider(model_name: str) -> str:
            if not model_name: return "groq"
            model_lower = model_name.lower()
            if model_lower.startswith("gpt-") or model_lower.startswith("o1-"): return "openai"
            if model_lower.startswith("claude-"): return "anthropic"
            if model_lower.startswith("gemini-"): return "gemini"
            if model_lower.startswith("deepseek-"): return "deepseek"
            if model_lower.startswith("mistral-") or model_lower.startswith("codestral-") or model_lower.startswith("open-mi"): return "mistral"
            return "groq" 

        i_model = intellect_model or getattr(config, "INTELLECT_MODEL")
        w_model = will_model or getattr(config, "WILL_MODEL")
        c_model = conscience_model or getattr(config, "CONSCIENCE_MODEL")

        # --- 1. Construct LLM Configuration ---
        llm_config = {
            "providers": {
                "openai": {
                    "type": "openai", 
                    "api_key": config.OPENAI_API_KEY
                },
                "groq": {
                    "type": "openai", 
                    "api_key": config.GROQ_API_KEY,
                    "base_url": "https://api.groq.com/openai/v1"
                },
                "anthropic": {
                    "type": "anthropic",
                    "api_key": config.ANTHROPIC_API_KEY
                },
                "gemini": {
                    "type": "gemini",
                    "api_key": config.GEMINI_API_KEY
                },
                "deepseek": {
                    "type": "openai",
                    "api_key": getattr(config, "DEEPSEEK_API_KEY", ""),
                    "base_url": "https://api.deepseek.com"
                },
                "mistral": {
                    "type": "openai",
                    "api_key": getattr(config, "MISTRAL_API_KEY", ""),
                    "base_url": "https://api.mistral.ai/v1"
                }
            },
            "routes": {
                "intellect": {
                    "provider": getattr(config, "INTELLECT_PROVIDER", detect_provider(i_model)), 
                    "model": i_model
                },
                "will": {
                    "provider": getattr(config, "WILL_PROVIDER", detect_provider(w_model)),
                    "model": w_model
                },
                "conscience": {
                    "provider": getattr(config, "CONSCIENCE_PROVIDER", detect_provider(c_model)),
                    "model": c_model
                }
            }
        }
        
        self.llm_provider = LLMProvider(llm_config)
        self.clients = self.llm_provider.clients

        # --- 2. RESTORE SYNC CLIENTS ---
        if config.GROQ_API_KEY:
            self.groq_client_sync = OpenAI(
                api_key=config.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )
        
        if config.OPENAI_API_KEY:
            self.openai_client_sync = OpenAI(api_key=config.OPENAI_API_KEY)
        else:
            self.openai_client_sync = None
            
        self.gemini_client = None
        if config.GEMINI_API_KEY:
            try:
                self.gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
            except Exception: pass

        # --- 3. Load System Prompts ---
        prompts_path = Path(__file__).parent / "system_prompts.json"
        try:
            with prompts_path.open("r", encoding="utf-8") as f:
                self.prompts = json.load(f)
        except Exception as e:
            self.log.error(f"Failed to load system_prompts.json: {e}")
            self.prompts = {}

        # --- 4. Load Persona and Values ---
        if value_profile_or_list:
            if isinstance(value_profile_or_list, dict) and "values" in value_profile_or_list:
                self.profile = value_profile_or_list
                self.values = self.profile["values"]
            elif isinstance(value_profile_or_list, list):
                self.profile, self.values = None, list(value_profile_or_list)
        elif value_set:
            self.profile, self.values = None, list(value_set)
        else:
            raise ValueError("Provide either value_profile_or_list or value_set")

        # --- 5. Initialize Services & Faculties ---
        self.log_dir = getattr(config, "LOG_DIR", "logs")
        self.log_template = getattr(config, "LOG_FILE_TEMPLATE", None)
        
        # --- LOGGING FIX: Use 'key' if available, else sanitized 'name' ---
        raw_key = (self.profile or {}).get("key")
        raw_name = (self.profile or {}).get("name", "custom")
        
        if raw_key:
             self.active_profile_name = raw_key
        else:
             import re
             # Sanitize name: replace non-alphanumeric with underscore
             self.active_profile_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', raw_name).lower()

        self.last_drift = 0.0
        self.mu_history = deque(maxlen=5)

        self.rag_service = RAGService(
            knowledge_base_name=(self.profile or {}).get("rag_knowledge_base")
        )

        # Initialize MCP Manager
        # We assume specific tools are enabled via config or default
        mcp_config = getattr(config, "MCP_CONFIG", {})
        self.mcp_manager = MCPManager(mcp_config)
        
        self.intellect_engine = IntellectEngine(
            llm_provider=self.llm_provider,
            profile=self.profile, 
            prompt_config=self.prompts.get("intellect_engine", {}),
            mcp_manager=self.mcp_manager
        )
        self.intellect_engine.retriever = self.rag_service.retriever

        self.will_gate = WillGate(
            llm_provider=self.llm_provider,
            values=self.values, 
            profile=self.profile, 
            prompt_config=self.prompts.get("will_gate", {})
        )

        self.conscience = ConscienceAuditor(
            llm_provider=self.llm_provider,
            values=self.values, 
            profile=self.profile, 
            prompt_config=self.prompts.get("conscience_auditor", {})
        )

        beta_val = spirit_beta if spirit_beta is not None else getattr(config, "SPIRIT_BETA", 0.9)
        self.spirit = SpiritIntegrator(self.values, beta=beta_val)

    def __del__(self):
        try:
            self.executor.shutdown(wait=False)
        except Exception:
            pass

    async def process_prompt(
        self, 
        user_prompt: str, 
        user_id: str, 
        conversation_id: str,
        user_name: Optional[str] = None,
        override_message_id: Optional[str] = None,
        org_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        The main entrypoint for processing a user's prompt.
        """
        message_id = override_message_id if override_message_id else str(uuid.uuid4()) 
        now_utc = datetime.now(timezone.utc)
        current_date_string = now_utc.strftime("Current Date: %A, %B %d, %Y. %H:%M:%S Z")
        prompt_with_date = f"{current_date_string}\n\nUSER QUERY: {user_prompt}"

        # --- 0. Pre-insertion for Live Reasoning ---
        try:
            # Ensure messages exist in DB so reasoning poller can find them IMMEDIATELLY
            history_check = db.fetch_chat_history_for_conversation(conversation_id, limit=1)
            new_title = db.set_conversation_title_from_first_message(conversation_id, user_prompt) if not history_check else None
            
            db.insert_memory_entry(conversation_id, "user", user_prompt)
            # Create the AI message placeholder immediately
            db.insert_memory_entry(conversation_id, "ai", "", message_id=message_id, audit_status="pending")
            
            # --- Initial Status ---
            db.update_message_reasoning(message_id, "Connecting to Intellect Faculty...")
        except Exception as e:
            import traceback
            trace = traceback.format_exc()
            msg = f"DEBUG: Pre-Insert CRASH: {str(e)} | Trace: {trace}"
            self.log.error(msg)
            return { "finalOutput": msg, "messageId": message_id }
        
        # Plugins
        plugin_context_data = {}
        plugin_client = self.clients.get("groq") 
        
        plugin_tasks = [
            handle_bible_scholar_commands(user_prompt, self.active_profile_name, self.log),
            # handle_fiduciary_commands(user_prompt, self.active_profile_name, self.log, plugin_client)  # Disabled for MCP
        ]
        plugin_results = await asyncio.gather(*plugin_tasks)
        for _, data in plugin_results:
            if data: plugin_context_data.update(data)
        
        # Memories
        memory_summary = db.fetch_conversation_summary(conversation_id)
        current_profile_json = db.fetch_user_profile_memory(user_id)
        
        temp_spirit_memory = db.load_spirit_memory(self.active_profile_name)
        if temp_spirit_memory is None:
             temp_spirit_memory = {}
        
        # --- FIX: Resolve Vector from Memory (Dict or List) for Feedback ---
        mu_memory = temp_spirit_memory.get("mu", {})

        current_mu = np.zeros(len(self.values))
        
        if isinstance(mu_memory, (list, np.ndarray)):
            # Legacy: Padding/Truncation
            old_arr = np.array(mu_memory)
            common_len = min(len(current_mu), old_arr.shape[0])
            current_mu[:common_len] = old_arr[:common_len]
        else:
            # Modern: Key Lookup
            # Sanitize value names for lookup
            from .faculties.utils import _norm_label
            for i, v in enumerate(self.values):
                v_name = v.get("value") or v.get("name") or "Unknown"
                current_mu[i] = mu_memory.get(_norm_label(v_name), 0.0)

        spirit_feedback = build_spirit_feedback(
            mu=current_mu,
            value_names=[v.get('value') or v.get('name') for v in self.values],
            drift=self.last_drift,
            recent_mu=list(self.mu_history)
        )
        
        

        # --- 1. Intellect Generation → Intent Proposal (no tool execution) ---
        intent, r_t, retrieved_context = await self.intellect_engine.generate(
            user_prompt=prompt_with_date,
            memory_summary=memory_summary,
            spirit_feedback=spirit_feedback,
            plugin_context=plugin_context_data,
            user_profile_json=current_profile_json,
            user_name=user_name,
            user_id=user_id,
            message_id=message_id
        )

        if intent is None:
            msg = f"Intellect failed: {self.intellect_engine.last_error or 'Unknown error'}"
            db.update_message_content(message_id, msg, audit_status="complete")
            return { "finalOutput": msg, "newTitle": new_title, "willDecision": "violation", "willReason": "Intellect failed.", "messageId": message_id }

        # --- Retry Metadata Tracking ---
        retry_metadata: Dict[str, Any] = {
            "was_retried": False,
            "original_draft": None,
            "violation_reason": None
        }

        # Typed variables shared by both execution paths
        a_t: str = ""
        D_t: str = "approve"
        E_t: str = ""

        # --- 2. Dynamic Loop Fork ---

        if intent["type"] == "text":
            # ------------------------------------------------------------------ #
            # Path A — Chatbot Mode: text response → Will Gate → optional Reflexion
            # ------------------------------------------------------------------ #
            a_t = intent.get("content") or ""

            if not a_t:
                msg = f"Intellect failed: {self.intellect_engine.last_error or 'Unknown error'}"
                db.update_message_content(message_id, msg, audit_status="complete")
                return { "finalOutput": msg, "newTitle": new_title, "willDecision": "violation", "willReason": "Intellect failed.", "messageId": message_id }

            # Will evaluation of the draft text
            db.update_message_reasoning(message_id, "Evaluating ethical compliance (Will Faculty)...")
            D_t, E_t = await self.will_gate.evaluate(
                user_prompt=user_prompt,
                draft_answer=a_t,
                conversation_summary=memory_summary
            )

            # --- Reflexion Loop (single retry on violation) ---
            if D_t == "violation":
                self.log.info(f"Will blocked first draft. Reason: {E_t}. Attempting Reflexion Retry.")
                db.update_message_reasoning(message_id, "Policy violation detected. Retrying with reflexion...")

                retry_metadata["was_retried"] = True
                retry_metadata["original_draft"] = a_t
                retry_metadata["violation_reason"] = E_t

                retry_template = self.prompts.get("will_retry", {}).get("template")
                if not retry_template:
                    retry_template = (
                        "{original_prompt_with_date}\n\n"
                        "--- INTERNAL GOVERNANCE FEEDBACK ---\n"
                        "Your previous draft response was blocked by the 'Will' gatekeeper.\n"
                        "Your Blocked Draft:\n\"\"\"\n{blocked_draft}\n\"\"\"\n\n"
                        "Violation Reason:\n{violation_reason}\n\n"
                        "INSTRUCTION: Rewrite your response to be fully compliant with the persona values and rules. "
                        "Analyze your blocked draft to understand what triggered the violation. "
                        "Address the user's intent safely. Do not mention this internal system correction or the block."
                    )

                retry_prompt = retry_template.format(
                    original_prompt_with_date=prompt_with_date,
                    blocked_draft=a_t,
                    violation_reason=E_t
                )

                retry_intent, r_t_retry, context_retry = await self.intellect_engine.generate(
                    user_prompt=retry_prompt,
                    memory_summary=memory_summary,
                    spirit_feedback=spirit_feedback,
                    plugin_context=plugin_context_data,
                    user_profile_json=current_profile_json,
                    user_name=user_name,
                    user_id=user_id,
                    message_id=message_id
                )

                a_t_retry: Optional[str] = (
                    retry_intent.get("content")
                    if retry_intent and retry_intent.get("type") == "text"
                    else None
                )

                if a_t_retry:
                    D_t_retry, E_t_retry = await self.will_gate.evaluate(
                        user_prompt=user_prompt,
                        draft_answer=a_t_retry,
                        conversation_summary=memory_summary
                    )

                    if D_t_retry == "approve":
                        self.log.info("Reflexion Retry Successful. Proceeding with safe response.")
                        a_t = a_t_retry
                        r_t = r_t_retry
                        retrieved_context = context_retry
                        D_t = D_t_retry
                        E_t = E_t_retry
                    else:
                        self.log.info(f"Reflexion Retry Failed. Still blocked. Reason: {E_t_retry}")
                        E_t = E_t_retry
                else:
                    self.log.warning("Reflexion Retry failed to generate text.")

        elif intent["type"] == "tool_call":
            # ------------------------------------------------------------------ #
            # Path B — Agent Mode: intercept tool call → Will Gate → execute/block
            # ------------------------------------------------------------------ #
            tool_name: str = intent["tool_name"]
            parameters: Dict[str, Any] = intent["parameters"]

            # Will Gate evaluates the tool intent BEFORE any execution
            db.update_message_reasoning(message_id, "Will gating tool request...")
            tool_decision, tool_reason = await self.will_gate.evaluate_tool_intent(
                tool_name=tool_name,
                parameters=parameters,
                profile=self.profile or {}
            )

            if tool_decision == "approve":
                # Bounded tool execution loop — the Intellect may request several tools
                # sequentially before it has enough information to synthesize a text answer.
                # Each tool is individually gated by WillGate before execution.
                MAX_AGENT_TURNS = 5
                agent_history = [prompt_with_date]
                current_tool_name = tool_name
                current_parameters = parameters
                next_intent = intent  # start with the initial tool_call intent

                for agent_turn in range(MAX_AGENT_TURNS):
                    db.update_message_reasoning(
                        message_id,
                        f"Executing contained tool action ({agent_turn + 1}/{MAX_AGENT_TURNS}): {current_tool_name}..."
                    )
                    
                    # 1. Append the model's raw thought signature or generic note
                    raw_turn = next_intent.get("_gemini_raw_turn") if isinstance(next_intent, dict) else None
                    if raw_turn:
                        from google.genai import types
                        agent_history.append(types.Content(**raw_turn))
                    else:
                        agent_history.append(f"SYSTEM OBSERVATION: Model requested tool {current_tool_name}.")

                    try:
                        tool_result = await self.mcp_manager.execute_tool(
                            current_tool_name, current_parameters, user_id=user_id
                        )
                    except Exception as exc:
                        self.log.error(f"Orchestrator: Tool '{current_tool_name}' raised: {exc}")
                        tool_result = f"ERROR: tool execution failed — {exc}"

                    self.log.info(
                        f"Orchestrator: Tool '{current_tool_name}' executed. "
                        f"Result snippet: {str(tool_result)[:120]}"
                    )
                    
                    # 3. Construct the tool response using the new SDK
                    from google.genai import types
                    tool_part = types.Part.from_function_response(name=current_tool_name, response={"result": tool_result})
                    agent_history.append(types.Content(role="user", parts=[tool_part]))

                    # Ask Intellect to synthesize — it may produce text or request another tool
                    next_intent, r_t, retrieved_context = await self.intellect_engine.generate(
                        user_prompt=agent_history,
                        memory_summary=memory_summary,
                        spirit_feedback=spirit_feedback,
                        plugin_context=plugin_context_data,
                        user_profile_json=current_profile_json,
                        user_name=user_name,
                        user_id=user_id,
                        message_id=message_id
                    )

                    if next_intent is None or next_intent.get("type") == "text":
                        # Intellect produced a text answer — exit the tool loop
                        break

                    # Intellect wants another tool — gate it before the next iteration
                    current_tool_name = next_intent["tool_name"]
                    current_parameters = next_intent["parameters"]

                    db.update_message_reasoning(message_id, "Will gating tool request...")
                    follow_decision, follow_reason = await self.will_gate.evaluate_tool_intent(
                        tool_name=current_tool_name,
                        parameters=current_parameters,
                        profile=self.profile or {}
                    )

                    if follow_decision != "approve":
                        self.log.warning(
                            f"WillGate blocked follow-up tool '{current_tool_name}'. "
                            f"Reason: {follow_reason}"
                        )
                        agent_history.append(
                            f"SYSTEM OBSERVATION: The Will gatekeeper rejected the follow-up "
                            f"command '{current_tool_name}'. Reason: {follow_reason}. "
                            f"Synthesize a response using only the information gathered so far."
                        )
                        # Force a final synthesis pass with the block notice appended
                        next_intent, r_t, retrieved_context = await self.intellect_engine.generate(
                            user_prompt=agent_history,
                            memory_summary=memory_summary,
                            spirit_feedback=spirit_feedback,
                            plugin_context=plugin_context_data,
                            user_profile_json=current_profile_json,
                            user_name=user_name,
                            user_id=user_id,
                            message_id=message_id
                        )
                        break
                else:
                    # Hit MAX_AGENT_TURNS without getting text — force synthesis
                    self.log.warning(
                        f"Orchestrator: Hit MAX_AGENT_TURNS ({MAX_AGENT_TURNS}). "
                        f"Forcing final synthesis."
                    )
                    agent_history.append(
                        "SYSTEM OBSERVATION: Maximum tool steps reached. "
                        "Synthesize the best possible answer from information gathered so far."
                    )
                    next_intent, r_t, retrieved_context = await self.intellect_engine.generate(
                        user_prompt=agent_history,
                        memory_summary=memory_summary,
                        spirit_feedback=spirit_feedback,
                        plugin_context=plugin_context_data,
                        user_profile_json=current_profile_json,
                        user_name=user_name,
                        user_id=user_id,
                        message_id=message_id
                    )

                a_t = (
                    next_intent.get("content") or ""
                    if next_intent and next_intent.get("type") == "text"
                    else "I was unable to produce a response after executing the requested tools."
                )

                # Final Will Gate check on the synthesized text before it reaches the user
                db.update_message_reasoning(message_id, "Evaluating ethical compliance (Will Faculty)...")
                D_t, E_t = await self.will_gate.evaluate(
                    user_prompt=user_prompt,
                    draft_answer=a_t,
                    conversation_summary=memory_summary
                )

            else:
                # Tool blocked — feed rejection back to Intellect for Agentic Reflexion
                self.log.warning(f"WillGate blocked tool '{tool_name}'. Reason: {tool_reason}")
                observation = (
                    f"SYSTEM OBSERVATION: The Will gatekeeper rejected the command '{tool_name}'. "
                    f"Reason: {tool_reason}. "
                    f"Do not attempt to call this tool again. "
                    f"Apologize to the user and, if possible, suggest a compliant alternative."
                )

                reflexion_intent, r_t, retrieved_context = await self.intellect_engine.generate(
                    user_prompt=f"{prompt_with_date}\n\n{observation}",
                    memory_summary=memory_summary,
                    spirit_feedback=spirit_feedback,
                    plugin_context=plugin_context_data,
                    user_profile_json=current_profile_json,
                    user_name=user_name,
                    user_id=user_id,
                    message_id=message_id
                )

                a_t = (
                    reflexion_intent.get("content") or ""
                    if reflexion_intent and reflexion_intent.get("type") == "text"
                    else f"I'm sorry, I was unable to complete that action. {tool_reason}"
                )
                # Agentic Reflexion text is considered pre-approved; the Will Gate already
                # intervened upstream.  We mark it approved so the success path runs.
                D_t = "approve"
                E_t = f"Tool '{tool_name}' blocked: {tool_reason}. Agentic Reflexion triggered."

        # --- 3. Final Decision (Block or Allow) ---
        if D_t == "violation":
            suppression_message = f"🛑 **Blocked**\n\nReason: {E_t}"
            S_p = await self._get_prompt_suggestions(user_prompt, (self.profile or {}).get("will_rules", []))
            db.update_message_content(message_id, suppression_message, audit_status="complete") 
            self._append_log({
                "userPrompt": user_prompt, 
                "blockedDraft": a_t,
                "finalOutput": suppression_message, 
                "willDecision": D_t, 
                "willReason": E_t, 
                "willReason": E_t, 
                "retryMetadata": retry_metadata, 
                "policyId": (self.profile or {}).get("policy_id"),
                "userId": user_id,
                "orgId": org_id or (self.profile or {}).get("org_id"),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            return { "finalOutput": suppression_message, "newTitle": new_title, "willDecision": D_t, "willReason": E_t, "activeProfile": self.active_profile_name, "activeValues": self.values, "suggestedPrompts": S_p, "messageId": message_id }

        # --- 4. Success: Update and Audit ---
        db.update_message_content(message_id, a_t, audit_status="pending")
        
        snapshot = { "t": int(temp_spirit_memory.get("turn", 0)) + 1, "x_t": user_prompt, "a_t": a_t, "r_t": r_t, "memory_summary": memory_summary, "retrieved_context": retrieved_context, "user_id": user_id, "org_id": org_id }
        
        # Pass retry_metadata to the audit thread
        self.executor.submit(self._run_audit_thread, snapshot, D_t, E_t, message_id, spirit_feedback, retry_metadata)
        
        if hasattr(self, 'groq_client_sync'):
            self.executor.submit(self._run_summarization_thread, conversation_id, memory_summary, user_prompt, a_t)
        
        if getattr(self.config, "ENABLE_PROFILE_EXTRACTION", False):
            if hasattr(self.config, "SUMMARIZER_MODEL"):
                 self.executor.submit(self._run_profile_update_thread, user_id, current_profile_json, user_prompt, a_t)

        return { 
            "finalOutput": a_t, "newTitle": new_title, "willDecision": D_t, "willReason": E_t, 
            "activeProfile": self.active_profile_name, "activeValues": self.values, "messageId": message_id, "suggestedPrompts": [] 
        }

    def _append_log(self, log_entry: Dict[str, Any]):
        log_path = Path(self.log_dir)
        if self.log_template:
            try:
                # Mock timestamp matching format in Orchestrator
                ts = datetime.fromisoformat(log_entry.get("timestamp").replace("Z", "+00:00"))
                fname = ts.strftime(self.log_template.format(profile=self.active_profile_name))
                log_path = log_path / fname
            except Exception as e:
                self.log.error(f"Failed to generate log filename for {self.active_profile_name}: {e}")
                return

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f: 
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            self.log.error(f"Failed to write log entry to {log_path}: {e}")
