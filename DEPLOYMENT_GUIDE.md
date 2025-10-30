# How to Deploy Your Tennis ML Model Web App

## Quick Options (Easiest to Hardest)

### Option 1: Render.com (Recommended - Free & Easy) ⭐

**Steps:**

1. **Push your code to GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin YOUR_GITHUB_REPO_URL
   git push -u origin main
   ```

2. **Go to [render.com](https://render.com)** and sign up (free)

3. **Create a new Web Service:**
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Fill in:
     - **Name:** tennis-ml-predictor (or any name)
     - **Runtime:** Python 3
     - **Build Command:** `pip install -r requirements.txt`
     - **Start Command:** `gunicorn app:app`
     - **Environment Variables:** (optional)
       - `ODDS_API_KEY` = your_api_key (if you have one)

4. **Click "Create Web Service"** - Render will deploy automatically!

**Important:** Add these files (see below):
- `Procfile` (for Render compatibility)
- `runtime.txt` (specify Python version)

---

### Option 2: Railway.app (Also Free & Easy)

1. **Go to [railway.app](https://railway.app)** and sign up
2. **Click "New Project"** → "Deploy from GitHub repo"
3. **Connect your GitHub repository**
4. **Railway auto-detects Flask** and deploys!

**Note:** Add `Procfile` (see below) for best results.

---

### Option 3: PythonAnywhere (Good for Python)

1. **Go to [pythonanywhere.com](https://www.pythonanywhere.com)** (free tier available)
2. **Upload your files** via web interface
3. **Configure WSGI** file to point to `app.py`
4. **Reload** web app

---

### Option 4: Heroku (Paid, but reliable)

1. **Install Heroku CLI:** `brew install heroku/brew/heroku` (Mac)
2. **Login:** `heroku login`
3. **Create app:** `heroku create your-app-name`
4. **Deploy:** `git push heroku main`

**Note:** Heroku now has paid plans, but you can use the free alternatives above.

---

## Required Files for Deployment

I'll create these files for you:
1. `Procfile` - Tells the platform how to run your app
2. `runtime.txt` - Specifies Python version
3. `.gitignore` - Excludes unnecessary files from git

---

## Important Notes

### Before Deploying:

1. **Large Files:** Your `.pkl` model files and CSV data files might be large. Consider:
   - Using Git LFS (Large File Storage) for large files
   - Or hosting data/models on cloud storage (S3, etc.)
   - Models are ~few MB, should be fine

2. **Port Configuration:** 
   - Update `app.py` to use `os.environ.get('PORT', 5001)` for cloud platforms
   - I'll update this for you

3. **Environment Variables:**
   - Set `ODDS_API_KEY` in your platform's environment settings
   - Platform will inject `PORT` automatically

4. **Data Files:**
   - Make sure `data/processed/` files are in your repo
   - Or use cloud storage for them

---

## Quick Start (Render.com Example)

1. I'll create the deployment files below
2. Push to GitHub
3. Connect to Render
4. Done! ✅

Your app will be live at: `https://tennis-ml-predictor.onrender.com` (or your chosen name)

---

## Troubleshooting

### Common Issues:

- **"Module not found"**: Make sure `requirements.txt` has all dependencies
- **"Port already in use"**: Use `os.environ.get('PORT', 5001)` 
- **"Memory error"**: Large model files - consider optimizing or using cloud storage
- **Slow startup**: First request loads models - this is normal

---

Need help with a specific platform? Let me know!

