# Dacoola - AI Tech News Aggregator & Summarizer

## Overview

Dacoola automates the process of discovering, filtering, summarizing, and publishing AI and technology news articles. It scrapes RSS feeds, uses AI agents (powered by DeepSeek) to analyze content, generate SEO-friendly summaries and tags, find relevant images, and builds static HTML pages for the news site.

## Features

- **Automated News Scraping**: Monitors multiple RSS feeds for new articles.
- **AI-Powered Filtering**: Identifies interesting/significant news using configurable criteria.
- **Duplicate Detection**: Checks for semantic duplicates before processing.
- **AI Content Generation**:
  - Creates concise, SEO-optimized news briefs.
  - Generates relevant article tags.
  - Suggests catchy headlines (implementation noted in code).
- **Image Selection**: Finds relevant featured images using source scraping and SerpApi/CLIP.
- **Static Site Generation**: Builds HTML pages for each article using Jinja2 templates.
- **Dynamic Site Data**: Updates a central `site_data.json` for sidebars and potential future features.
