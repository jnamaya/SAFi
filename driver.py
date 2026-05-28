from uvicorn.workers import UvicornWorker

class AsyncioWorker(UvicornWorker):
    """
    Custom Uvicorn worker to force the use of the standard asyncio loop.
    This resolves compatibility issues with asgiref and uvloop.
    """
    CONFIG_KWARGS = {"loop": "asyncio"}
