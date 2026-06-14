import time
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import logging.config
from IngestionPipeline.logger import LOGGING_CONFIG
import yaml
logging.config.dictConfig(LOGGING_CONFIG)
root_logger = logging.getLogger()
logger = root_logger.getChild("runner")

class DirectoryWatcher(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            logger.info(f"New folder detected: {event.src_path}")
            print(f"New folder detected: {event.src_path}")
            # Trigger the ingestion pipeline here. For example, you can call a function or run a script.
            try:
                subprocess.run(["python", "graph.py", "--new_file", event.src_path], check=True)
            except Exception as e:
                logger.error(f"Error occurred while running ingestion script: {e}")


with open("config.yml", 'r') as f:
    config = yaml.safe_load(f)

PATH_TO_WATCH = config.get("DATA_PATH", "Subsidies Schemes Grants and Incentives")

if __name__ == "__main__":
    event_handler = DirectoryWatcher()
    observer = Observer()
    observer.schedule(event_handler, path=PATH_TO_WATCH, recursive=True)  # recursive=True watches subfolders too
    
    observer.start()

    try:
        while True:
            time.sleep(1)  # Keeps the program alive
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
