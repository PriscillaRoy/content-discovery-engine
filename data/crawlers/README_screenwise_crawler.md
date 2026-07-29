# Screenwise Archive.org Crawler

## Install

```bash
pip install -r requirements_screenwise.txt
```

Optional video feature analysis:

```bash
brew install ffmpeg
# or Ubuntu:
sudo apt install ffmpeg
```

Optional AI summaries:

```bash
ollama pull llama3.2
ollama serve
```

## Run crawler from Archive.org search

```bash
python screenwise_archive_crawler.py --target 50 --output screenwise_assets.json --output-py screenwise_assets.py --output-csv screenwise_assets.csv
```

## Verify and enrich your existing seed file only

```bash
python screenwise_archive_crawler.py --input-seed asset_seed_data.py --seed-only --target 50 --output verified_screenwise_assets.json --output-py verified_screenwise_assets.py
```

## Add actual video analysis

This uses ffprobe/ffmpeg against the Archive.org video URL to estimate runtime, scene cuts per minute, visual stimulation, and audio intensity.

```bash
python screenwise_archive_crawler.py --target 50 --analyze-video --max-video-analyze 20
```

## Add Ollama summaries

```bash
python screenwise_archive_crawler.py --target 50 --use-ollama
```

## Best practical production run

```bash
python screenwise_archive_crawler.py \
  --input-seed asset_seed_data.py \
  --target 100 \
  --pages-per-query 4 \
  --rows-per-page 75 \
  --analyze-video \
  --max-video-analyze 50 \
  --use-ollama \
  --output screenwise_assets.json \
  --output-py screenwise_assets.py \
  --output-csv screenwise_assets.csv
```
