# Deployment Guide

## Quick Deployment Options

### Render.com (Recommended)

1. **Push code to GitHub**
2. **Go to [render.com](https://render.com)** and sign up
3. **Create Web Service:**
   - Connect GitHub repository
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app.wsgi:application`
   - Environment Variables:
     - `KALSHI_ACCESS_KEY` (for Kalshi trading)
     - `KALSHI_PRIVATE_KEY_PATH` (path to private key)
     - `FLASK_ENV=production`
4. **Deploy** - Render handles the rest

### Other Platforms

- **Railway.app**: Auto-detects Flask, just connect GitHub
- **Heroku**: Use `git push heroku main` (requires paid plan)
- **PythonAnywhere**: Upload files and configure WSGI

## Required Files

- `Procfile` - Already configured
- `runtime.txt` - Python version
- `requirements.txt` - Dependencies

## Environment Variables

Set these in your deployment platform:
- `KALSHI_ACCESS_KEY` - Kalshi API access key
- `KALSHI_PRIVATE_KEY_PATH` - Path to Kalshi private key file
- `FLASK_ENV=production` - Production mode
- `PORT` - Auto-set by platform

## Notes

- Model files (`.pkl`) are included in repo
- First startup loads models (may take 30-60 seconds)
- Use Git LFS for very large files if needed
