#!/bin/sh

# run this from top level (stories-pipeline) directory,
# after creating a virtual environment, activating, and
# installing requirements.

rm -rf /tmp/metadata_worker
mkdir /tmp/metadata_worker


python -m scripts.configure -f plumbing.json configure
supervisord -c supervisord.conf