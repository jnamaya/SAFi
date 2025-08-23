import asyncio
from safi_app.core.orchestrator import SAFi
from safi_app.core.values import list_profiles, get_profile
from safi_app.config import Config

PROMPT = "What is the view of the Church on marriage?"

async def run_one(name: str):
    prof = get_profile(name)
    safi = SAFi(config=Config, value_profile_or_list=prof)
    res = await safi.process_prompt(PROMPT, user_id=f"test-{name}", conversation_id=f"conv-{name}")
    print(f"\n=== {name.upper()} ===")
    print("Worldview:", prof.get("worldview")[:140], "...")
    print("Values:", [v["value"] for v in prof["values"]])
    print("\nAnswer:\n", res.get("finalOutput", "")[:800])

async def main():
    for name in list_profiles():
        await run_one(name)

if __name__ == "__main__":
    asyncio.run(main())
