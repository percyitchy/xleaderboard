import asyncio
import logging
import time
from functools import wraps
from typing import Callable, Any, Coroutine, Optional

# Настройка базового логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RateLimiter:
    """
    Token Bucket Rate Limiter.
    """
    def __init__(self, rate: float, period: float = 1.0):
        self.rate = rate
        self.period = period
        self.tokens = rate
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            time_passed = now - self.last_update
            self.tokens += time_passed * (self.rate / self.period)
            if self.tokens > self.rate:
                self.tokens = self.rate
            self.last_update = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) * (self.period / self.rate)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                self.tokens = 0
                self.last_update = time.monotonic()
            else:
                self.tokens -= 1

def retry_async(
    retries: Optional[int] = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 16.0,
    exceptions: tuple = (Exception,)
) -> Callable:
    """
    Декоратор для повторного выполнения асинхронной функции при возникновении исключений.

    :param retries: Максимальное количество попыток. Если None, попытки бесконечны.
    :param delay: Начальная задержка между попытками в секундах.
    :param backoff: Множитель для увеличения задержки после каждой попытки.
    :param max_delay: Максимальная задержка между попытками в секундах.
    :param exceptions: Кортеж исключений, при которых следует повторять попытку.
    """
    def decorator(func: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Coroutine[Any, Any, Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            attempt = 0
            while True:
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    attempt += 1
                    if retries is not None and attempt >= retries:
                        error_msg = str(e) if str(e) else repr(e)
                        logging.error(
                            f"Функция '{func.__name__}' не выполнилась после {retries} попыток. Последняя ошибка: {error_msg} (тип: {type(e).__name__})"
                        )
                        raise  # Повторно вызываем исключение после всех неудачных попыток

                    error_msg = str(e) if str(e) else repr(e)
                    status_code = getattr(e, 'status', 'N/A')
                    retry_info = f"{attempt}/{retries}" if retries is not None else f"{attempt}/∞"
                    logging.warning(
                        f"Попытка {retry_info} для '{func.__name__}' не удалась. Код: {status_code}. Ошибка: {error_msg} (тип: {type(e).__name__}). "
                        f"Повтор через {current_delay:.2f} сек..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay = min(current_delay * backoff, max_delay)
        return wrapper
    return decorator
