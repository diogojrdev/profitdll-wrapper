"""Events layer (dispatcher).

DLL callbacks run on ProfitDLL's internal ConnectorThread.
Thread safety architecture ("lean callback -> queue -> dispatcher"):
1. C callback converts raw memory into immutable dataclasses and pushes event into queue.
2. EventDispatcher drains queue on application thread and delivers events to user handlers.
3. User exceptions inside event handlers are safely caught, logged, and isolated from DLL.
"""
