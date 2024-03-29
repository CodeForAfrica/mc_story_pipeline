import datetime
import argparse
import json
import time
from pathlib import Path
from scrapy import signals
from scrapy.crawler import CrawlerProcess
from scrapy.signalmanager import dispatcher

from filesystem.filesystem_interface import pipeline_filesystem_interface
from filesystem.state import WorkState

from pipeline.worker import Worker, run

from .batcher import sample_backup_rss, rss_batcher
from .BatchSpider import BatchSpider


class HtmlFetchingWorker(Worker):

    # , date:datetime, batch_index:int, num_batches:int, sample_size:int):
    def __init__(self, process_name: str, descr: str):
        super().__init__(process_name, descr)
        """
        self.date = date
        self.batch_index = batch_index
        self.num_batches = num_batches
        self.sample_size = sample_size
        """

    def define_options(self, ap: argparse.ArgumentParser):
        super().define_options(ap)

        ap.add_argument("--date",
                        type=lambda s: datetime.datetime.strptime(
                            s, '%Y-%m-%d'),
                        help="The date (as a string in %Y-%m-%d) being scraped for",
                        required=True)

        ap.add_argument("--num_batches",
                        type=int,
                        help="The number of batches being executed",
                        required=True)

        ap.add_argument("--batch_index",
                        type=int,
                        help="The batch index which this workerwill run on",
                        required=True)

        ap.add_argument("--sample_size",
                        type=int,
                        help="For testing, how much of the rss to sample before batching. 0 means all",
                        default=0)

    def spider_closed(self, chan, spider, reason):
        fs = pipeline_filesystem_interface(self.args.date)
        dir_path = fs.content_path_str
        worker = Worker("meta-gen", "publish folder to Metadata Queue")
        worker.send_items(chan, dir_path)
        print(
            f"Spider {spider} finished with reason: {reason}, dir path: {dir_path}")

    def main_loop(self, conn, chan):
        # Only the first job will actually generate the batches
        if self.args.batch_index == 0:
            # grab rss content, and generate batches
            fs = pipeline_filesystem_interface(self.args.date)
            source_rss = sample_backup_rss(
                self.args.date, sample_size=self.args.sample_size)
            fs.init_rss(source_rss)
            batches, batch_map = rss_batcher(source_rss, self.args.num_batches)
            fs.init_batches(batches, batch_map)

        # Otherwise give the batching process a head-start, so there's not a fs conflict
        else:
            time.sleep(1)
            fs = pipeline_filesystem_interface(self.args.date)

        # Then, using the little 'ready' file as a latch, wait.
        while not fs.get_status() >= WorkState.BATCHES_READY:
            time.sleep(10)

        process = CrawlerProcess()
        spider = BatchSpider

        dispatcher.connect(self.spider_closed(
            chan=chan, spider=spider, reason=None), signal=signals.spider_closed, weak=False)
        # For now, just send the send_items method into the scrapy worker. There might be a better way down the line

        # spider = BatchSpider(date=self.args.date,batch_index=self.args.batch_index, send_items=self.send_items, chan=chan)
        process.crawl(BatchSpider, date=self.args.date,
                      batch_index=self.args.batch_index, send_items=self.send_items, chan=chan)

        # process.crawl(spider)
        process.start()

    def keep_alive(self):
        pass  # This is a callback loop that just keeps the thing alive.


run(HtmlFetchingWorker, "demo-fetcher", "Demo HTML-fetching pipeline worker")
