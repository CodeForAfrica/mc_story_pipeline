"""
metadata extractor worker
"""
import os
import datetime as dt
import gzip
import time
import json
import logging
import sys
from typing import List

# PyPI:
import mcmetadata

# local:
from pipeline.worker import Worker, ListConsumerWorker, run

logger = logging.getLogger(__name__)


def load_html(item):
    # Check for saved headers (from recently downloaded HTML)
    # to determine original Content-Type???

    # With old html downloaded from S3, any Content-Type headers have
    # been lost, and not everything on the web is UTF-8, so we have to
    # read the file as binary bytes and try different decoding schemes.

    html_filename = item["html_file"]
    if html_filename.endswith('.gz'):
        # basename = html_filename[0:-3]
        with gzip.GzipFile(html_filename) as f:
            html_bytes = f.read()
    else:
        basename = html_filename
        with open(html_filename, 'rb') as f:
            html_bytes = f.read()

    json_filename = item["json_file"]
    with open(json_filename, 'rb') as f:
        content = f.read()
    try:
        meta_item = json.loads(content)
        item_url = meta_item.get("rss_entry").get("link")
    except:
        print(f"Error decoding JSON content from: {json_filename}")

    # look for BOM first?
    try:
        html = html_bytes.decode()
    except:
        try:
            html = html_bytes.decode('utf-16')
        except:
            try:
                html = html_bytes.decode('utf-16')
            except:
                # XXX fall back to ISO-8859-1 (Latin-1)?
                # It would be wise to see if iso-8859-1 decode of
                # arbitrary binary EVER fails (if it doesn't,
                # it could return trash)!
                print("could not decode", html_filename)
                return None, None

    path_dir = os.path.dirname(json_filename)
    file_basename = os.path.splitext(os.path.basename(json_filename))[
        0].replace(".html%-http_meta", "")

    basename = os.path.join(path_dir, file_basename)

    return basename, item_url, html


class Meta(ListConsumerWorker):
    """
    Takes folder path and process html files
    """
    INPUT_BATCH_MSGS = 1  # process 1 message at a time

    def __init__(self, process_name: str, descr: str):
        super().__init__(process_name, descr)
        self.folders_path: List[str] = []

    def process_message(self, chan, method, properties, decoded):
        self.folders_path.append(decoded)

    def end_of_batch(self, chan):
        for folder_path in self.folders_path:
            for root, dirs, files in os.walk(folder_path):
                html_files = [
                    file_name for file_name in files if file_name.endswith(".html%-raw.html")]

                for html_file_name in html_files:
                    html_file_path = os.path.join(root, html_file_name)
                    json_file_path = html_file_path.replace(
                        ".html%-raw.html", ".html%-http_meta.json")
                    item = {"json_file": json_file_path,
                            "html_file": html_file_path}
                    self.process_item(item)
                    time.sleep(5)

            self.send_to_elastic_queue(chan, folder_path)

    def process_item(self, item):
        basename, item_url, html = load_html(item)
        if html is None:
            # XXX shunt message to quarantine?
            return None

        try:
            meta = mcmetadata.extract(item_url, html)
            # make JSON safe:
            if isinstance(meta['publication_date'], dt.datetime):
                meta['publication_date'] = meta['publication_date'].isoformat()
        except mcmetadata.exceptions.BadContentError:
            # XXX shunt message to quarantine?
            meta = {}

        item.pop("html_file")
        item.pop("json_file")
        item['meta'] = meta
        print(f"Items: {item}")
        json_fname = basename + ".html%-extracted_meta.json"
        with open(json_fname, 'w') as f:
            json.dump(item, f)
        logger.info(f"wrote {json_fname}")

        return None             # no output message generated for now

    def send_to_elastic_queue(self, chan, items):
        worker = Worker("elastic-gen", "publish folder to arhchiving Queue")
        logger.info("sending to elastic queue...")
        print(items)
        worker.send_items(chan, items)
        sys.stdout.flush()
        time.sleep(1)


if __name__ == '__main__':
    run(Meta, "meta-consume", "metadata extractor worker")
