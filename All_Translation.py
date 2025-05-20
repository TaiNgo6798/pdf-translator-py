import time
import LLMS_translation as lt
import asyncio
from functools import wraps
import threading
from queue import Queue

# 创建一个信号量，限制并发为1（串行处理）
translation_semaphore = asyncio.Semaphore(1)
# 创建一个队列处理锁，确保队列操作线程安全
queue_lock = threading.Lock()
# 创建翻译请求队列
translation_queue = Queue()
# 标记队列处理器是否已启动
queue_processor_started = False

def retry_on_error(max_retries=2, delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper_sync(*args, **kwargs):
            retries = 0
            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries <= max_retries:
                        print(f"Error occurred: {str(e)}")
                        print(f"Retrying... (Attempt {retries} of {max_retries})")
                        time.sleep(delay)
                    else:
                        print(f"Max retries reached. Skipping... Final error: {str(e)}")
                        return None
            return None

        async def wrapper_async(*args, **kwargs):
            retries = 0
            while retries <= max_retries:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries <= max_retries:
                        print(f"Error occurred: {str(e)}")
                        print(f"Retrying... (Attempt {retries} of {max_retries})")
                        await asyncio.sleep(delay)
                    else:
                        print(f"Max retries reached. Skipping... Final error: {str(e)}")
                        return None
            return None

        return wrapper_async if asyncio.iscoroutinefunction(func) else wrapper_sync
    return decorator

# 队列处理器函数
def process_translation_queue():
    global queue_processor_started

    # 在这里只创建一次事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    while True:
        task = translation_queue.get()
        if task is None:  # 终止信号
            translation_queue.task_done()
            break
        try:
            func, args, kwargs, result_holder = task
            # 这里直接用上面创建的 loop 执行
            result = loop.run_until_complete(func(*args, **kwargs))
            result_holder['result'] = result
        except Exception as e:
            print(f"Error processing translation task: {str(e)}")
            result_holder['result'] = None
        finally:
            translation_queue.task_done()

    # 跳出循环后，才一次性关闭事件循环
    # 先清理异步生成器
    loop.run_until_complete(loop.shutdown_asyncgens())
    # 然后再 close
    loop.close()
# 启动队列处理线程
def ensure_queue_processor():
    global queue_processor_started
    with queue_lock:
        if not queue_processor_started:
            threading.Thread(target=process_translation_queue, daemon=True).start()
            queue_processor_started = True

class Online_translation:
    def __init__(self, original_language, target_language, translation_type, texts_to_process=[]):
        self.model_name = f"opus-mt-{original_language}-{target_language}"
        self.original_text = texts_to_process
        self.target_language = target_language
        self.original_lang = original_language
        self.translation_type = translation_type
        # 确保队列处理器已启动
        ensure_queue_processor()

    def run_async(self, coro):
        # 创建结果容器
        result_holder = {'result': None}
        
        # 将协程包装为任务并放入队列
        translation_queue.put((self._run_coro_with_semaphore, [coro], {}, result_holder))
        
        # 等待任务完成
        translation_queue.join()
        
        # 返回结果
        return result_holder['result']
    
    async def _run_coro_with_semaphore(self, coro):
        # 使用信号量确保串行执行
        async with translation_semaphore:
            return await coro

    def translation(self):
        print('翻译api', self.translation_type)
        if self.translation_type == 'openai':
            translated_list = self.run_async(self.openai_translation())
        return translated_list

    @retry_on_error()
    async def openai_translation(self):
        translator = lt.Openai_translation()
        translated_texts = await translator.translate(
            texts=self.original_text,
            original_lang=self.original_lang,
            target_lang=self.target_language
        )
        return translated_texts

# 确保程序退出前清理资源
import atexit

@atexit.register
def cleanup():
    # 发送终止信号
    if queue_processor_started:
        translation_queue.put(None)
        # 给队列处理器一些时间来处理终止信号
        translation_queue.join()

t = time.time()

def split_text_to_fit_token_limit(text, encoder, index_text, max_length=280):
    tokens = encoder.encode(text)
    if len(tokens) <= max_length:
        return [(text, len(tokens), index_text)]

    split_points = [i for i, token in enumerate(tokens) if encoder.decode([token]).strip() in [' ', '.', '?', '!','！','？','。']]
    parts = []
    last_split = 0
    for i, point in enumerate(split_points + [len(tokens)]):
        if point - last_split > max_length:
            part_tokens = tokens[last_split:split_points[i - 1]]
            parts.append((encoder.decode(part_tokens), len(part_tokens), index_text))
            last_split = split_points[i - 1]
        elif i == len(split_points):
            part_tokens = tokens[last_split:]
            parts.append((encoder.decode(part_tokens), len(part_tokens), index_text))

    return parts

def process_texts(texts, encoder):
    processed_texts = []
    for i, text in enumerate(texts):
        sub_texts = split_text_to_fit_token_limit(text, encoder, i)
        processed_texts.extend(sub_texts)
    return processed_texts

def calculate_split_points(processed_texts, max_tokens=425):
    split_points = []
    current_tokens = 0

    for i in range(len(processed_texts) - 1):
        current_tokens = processed_texts[i][1]
        next_tokens = processed_texts[i + 1][1]

        if current_tokens + next_tokens > max_tokens:
            split_points.append(i)

    split_points.append(len(processed_texts) - 1)

    return split_points