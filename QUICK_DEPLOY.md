# Quick Deploy Guide - Tennis ML Predictor

## 🚀 Fastest Way: Render.com (5 minutes)

### Step 1: Push to GitHub

```bash
# Initialize git (if not already)
git init
git add .
git commit -m "Ready for deployment"

# Create a new repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/tennis-ml-model.git
git branch -M main
git push -u origin main
```

### Step 2: Deploy on Render

1. Go to **[render.com](https://render.com)** → Sign up (free)

2. Click **"New +"** → **"Web Service"**

3. Connect your GitHub account and select your `tennis-ml-model` repo

4. Configure:
   - **Name:** `tennis-ml-predictor` (or any name)
   - **Region:** Choose closest to you
   - **Branch:** `main`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`

5. Click **"Create Web Service"**

6. Wait 5-10 minutes for first deployment

7. **Done!** Your app will be live at: `https://tennis-ml-predictor.onrender.com`

---

## Alternative: Railway.app (Even Easier)

1. Go to **[railway.app](https://railway.app)** → Sign up
2. **"New Project"** → **"Deploy from GitHub repo"**
3. Select your repo
4. Railway auto-detects Flask and deploys automatically!
5. Done! ✅

---

## What I've Created for You:

✅ **`Procfile`** - Tells Render/Railway how to run your app  
✅ **`runtime.txt`** - Specifies Python version  
✅ **`.gitignore`** - Excludes unnecessary files  
✅ **Updated `app.py`** - Uses PORT from environment  
✅ **Updated `requirements.txt`** - Added gunicorn  

---

## Optional: Add Environment Variables

In your Render/Railway dashboard, add:
- **Key:** `ODDS_API_KEY`  
- **Value:** `your_api_key_here`  

(Only if you have a real betting API key)

---

## Your App URL

After deployment, you'll get a URL like:
- Render: `https://tennis-ml-predictor.onrender.com`
- Railway: `https://your-app-name.railway.app`

Share this URL with anyone! 🎾

---

## Notes:

- **First load is slow** (loads models) - this is normal
- **Free tier** may sleep after inactivity (Render/Railway)
- **All your data/models** will be included in the deployment

Need help? Check `DEPLOYMENT_GUIDE.md` for more details!

