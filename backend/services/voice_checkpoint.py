"""Short-lived voice checkpoints. Audio, transcripts and contact details stay out of Redis."""

from __future__ import annotations

from uuid import uuid4

from redis.exceptions import WatchError

from backend.services.redis_client import get_redis


class VoiceCheckpoint:
    ttl_seconds = 3600

    def __init__(self, call_sid: str, dispatch_id: str, donor_id: str):
        self.key = f"haemnet:voice:v1:{call_sid}"
        self.dispatch_id = dispatch_id
        self.donor_id = donor_id
        self.owner = uuid4().hex
        self.client = get_redis()

    async def can_resume(self) -> bool:
        if self.client is None:
            return False
        saved = await self.client.hgetall(self.key)
        return (
            saved.get("dispatch") == self.dispatch_id
            and saved.get("donor") == self.donor_id
            and saved.get("ended") != "1"
        )

    async def attach(self, default_mode: str) -> dict:
        if self.client is None:
            return {"mode": default_mode}
        async with self.client.pipeline(transaction=True) as pipe:
            while True:
                try:
                    await pipe.watch(self.key)
                    saved = await pipe.hgetall(self.key)
                    if saved and (saved["dispatch"], saved["donor"]) != (self.dispatch_id, self.donor_id):
                        raise ValueError("Voice checkpoint belongs to another call")
                    mode = saved.get("mode", default_mode)
                    pipe.multi()
                    pipe.hset(
                        self.key,
                        mapping={
                            "dispatch": self.dispatch_id,
                            "donor": self.donor_id,
                            "owner": self.owner,
                            "mode": mode,
                        },
                    )
                    pipe.expire(self.key, self.ttl_seconds)
                    await pipe.execute()
                    return {**saved, "mode": mode}
                except WatchError:
                    continue

    async def save(self, confirming: bool, attempts: int, *, ended: bool = False) -> bool:
        if self.client is None:
            return True
        async with self.client.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(self.key)
                if await pipe.hget(self.key, "owner") != self.owner:
                    return False
                pipe.multi()
                pipe.hset(self.key, mapping={"confirming": int(confirming), "attempts": attempts, "ended": int(ended)})
                pipe.expire(self.key, self.ttl_seconds)
                await pipe.execute()
                return True
            except WatchError:
                return False
