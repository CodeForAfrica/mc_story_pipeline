import os
import datetime
import sys
import json
import hashlib
import time
import logging
from typing import List
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from pipeline.worker import Worker, ListConsumerWorker, run
from scripts.configure import Plumbing

logger = logging.getLogger(__name__)


class ESConsumer(ListConsumerWorker):
    """
    Takes folderpath and process for ES ingest.
    """

    INPUT_BATCH_MSGS = 1  # process 1 message at a time

    def __init__(self, process_name: str, descr: str):
        super().__init__(process_name, descr)
        self.folders_path: List[str] = []
        self.index_name = "mediacloud_search_text"
        self.settings = {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "domain": {"type": "keyword"},
                    "first_captured": {"type": "date"},
                    "host": {"type": "keyword"},
                    "language": {"type": "keyword"},
                    "publication_date": {"type": "date"},
                    "snippet": {"type": "text", "fielddata": True},
                    "surt_url": {"type": "keyword"},
                    "text_extraction_method": {"type": "keyword"},
                    "title": {"type": "text", "fielddata": True},
                    "tld": {"type": "keyword"},
                    "url": {"type": "keyword"},
                }
            },
        }
        self.es_url = os.environ.get("ELASTIC_URL")
        self.create_elasticsearch_index(self.es_url)

    def process_message(self, chan, method, properties, decoded):
        self.folders_path.append(decoded)

    def end_of_batch(self, chan):
        documents = []
        folders_path = self.folders_path
        for folder_path in folders_path:
            for root, dirs, files in os.walk(folder_path):
                for file_name in files:
                    if ".html%-extracted_meta.json" in file_name:
                        logger.info(f"Files:{file_name}")
                        file_path = os.path.join(root, file_name)
                        content = self.read_file_content(file_path)
                        documents.append(content)
            self.ingest_to_elasticsearch(documents)
            self.send_to_archiving_queue(chan, folder_path)

        self.folders_path = []
        sys.stdout.flush()
        return None

    def read_file_content(self, filepath):
        with open(filepath, "r") as file:
            content = file.read()
        try:
            item = json.loads(content)
            meta = item.get("meta")

            if meta and isinstance(meta, dict) and meta:
                url = meta.get("normalized_url")

                url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
                document = {
                    "_index": self.index_name,
                    "_id": url_hash,
                    "_source": {
                        "domain": meta.get("canonical_domain"),
                        "first_captured": meta.get("publication_date"),
                        "host": meta.get("canonical_domain"),
                        "language": meta.get("language"),
                        "publication_date": meta.get("publication_date"),
                        "snippet": meta.get("text_content"),
                        "surt_url": None,
                        "text_extraction_method": None,
                        "title": meta.get("article_title"),
                        "tld": item.get("tld"),
                        "url": url,
                        "version": "1.0",
                    },
                }
                return document
            else:
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON content: {e}")
            return None

    def ingest_to_elasticsearch(self, documents=None):
        es = Elasticsearch(self.es_url)
        if documents:
            bulk(es, documents)

    def create_elasticsearch_index(self, es_url):
        es = Elasticsearch(self.es_url)
        es.indices.create(index=self.index_name,
                          body=self.settings, ignore=400)

    def send_to_archiving_queue(self, chan, items):
        worker = Worker("archiving-gen", "publish folder to arhchiving Queue")
        logger.info("sending to archiving queue...")
        worker.send_items(chan, items)
        sys.stdout.flush()
        time.sleep(1)


if __name__ == "__main__":
    run(ESConsumer, "elastic-consume", "get filepaths from Queue")
