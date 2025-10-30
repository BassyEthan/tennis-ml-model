# Deploy WITHOUT GitHub - Step by Step什么是

## Option 1: PythonAnywhere ⭐ EASIEST (No Git, No CLI)

**This is the simplest option - just upload files via web browser!**

### Steps:

1. **Sign up at [pythonanywhere.com](https://www.pythonanywhere.com)**
   - Free tier available (with some limitations)
   - No credit card needed

2. **Create a New Web App:**
   - After logging in, click **"Web"** tab
   - Click **"Add a new web app"**
   - Choose Python 3.11 (or latest available)
   - Choose **"Flask"** framework
   - Choose Python 3.11 and click **"Next"**

3. **Upload Your Files:**
   - Go to **"Files"** tab
   - Navigate to `/home/YOUR_USERNAME/mysite/` (or create a folder)
   - Upload these files/folders:
     ```
     app.py
     requirements.txt
     Procfile (optional)
     templates/ (entire folder)
     models/ (entire folder with .pkl files)
     data/processed/ (if needed)
     src/ (entire folder)
     ```
   - **Lecture:** You can upload files one by one OR use the "Bash console" to upload via `wget` or `curl`

4. **Install Dependencies:**
   - Go to **"Consoles"** tab → Start a **"Bash console"**
   - Run:
     ```bash
     pip3.11 install --user -r requirements.txt
     ```
   - This installs all your packages

5. **Configure WSGI File:**
   - Go to **"Web"** tab → Click on standard WSGI configuration file
   - Replace contents with:
     ```python
     import sys
     path = '/home/YOUR_USERNAME/mysite'
     if path not in sys.path:
         sys.path.insert(0, path)
     
     from app import app as application
     
     if __name__ == "__main__":
         application.run()
     ```
   - Replace `YOUR_USERNAME` with your actual PythonAnywhere username
   - Save

6. **Reload Web App:**
   - Go to **"Web"** tab
   - Click the green **"Reload"** button
   - Your app will be live at: `YOUR_USERNAME.pythonanywhere.com`

**Done!** 🎉

---

## Option 2: Fly.io (CLI, but No GitHub)

**Deploy directly from your computer using command line**

### Steps:

1. **Install Fly CLI:**
   ```bash
   curl -L https://fly.io/install.sh | sh
   ```

2. **Sign up:**
   ```bash
   fly auth signup
   ```

3. **Initialize Fly app:**
   ```bash
   cd /Users/ethanlung/Documents/projects/tennis-ml-model
   fly launch
   ```
   - Follow prompts (name your app, select region)
   - Say "no" when asked about Postgres or other services
   - This creates a `fly.toml` file

4. **Deploy:**
   ```bash
   fly deploy
   ```

5. **Done!** Your app will be at: `https://your-app-name.fly.dev`

**Note:** Fly.io has a free tier but requires a credit card.

---

## Option 3: Replit (No Git Required)

**Create project directly on Replit website**

### Steps:

1. **Go to [replit.com](https://replit.com)** → Sign up

2. **Create Repl:**
   - Click **"Create Repl"**
   - Choose **"Python"** template
   - Name it "tennis-ml-predictor"

3. **Upload Files:**
   - You can drag and drop files into Replit
   - OR use the file upload button
   - Upload all your files/folders

4. **Install Dependencies:**
   - In the Replit shell (bottom panel):
     ```bash
     pip install -r requirements.txt
     ```

5. **Run:**
   - Click the **"Run"** button
   - Replit will automatically create a web URL

**Note:** Free tier may have limitations, but no GitHub needed!

---

## Option 4: Heroku CLI (Local Deploy)

**Deploy directly from your computer (requires Heroku CLI)**

### Steps:

1. **Install Heroku CLI:**
   ```bash
   brew tap heroku/brew && brew install heroku
   ```

2. **Login:**
   ```bash
   heroku login
   ```

3. **Create App:**
   ```bash
   cd /Users/ethanlung/Documents/projects/tennis-ml-model
   heroku create your-app-name
   ```

4. **Deploy:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   heroku git:remote -a your-app-name
   git push heroku main
   ```

**Note:** Heroku now requires paid plans, but you can use free alternatives above.

---

## Recommendation Ranking:

1. **🥇 PythonAnywhere** - Easiest, web-based, no CLI, free tier
2. **🥈 Fly.io** - Good free tier, CLI-based, fast deployment
3. **🥉 Replit** - Very easy, good for testing, may have resource limits

---

## Quick Start: PythonAnywhere

If you want the EASIEST option (PythonAnywhere):
1. Sign up: https://www.pythonanywhere.com
2. Create Flask web app
3. Upload files via web interface
4. Install requirements in Bash console
5. Configure WSGI file
6. Reload

**Total time: ~15 minutes, no Git needed!**

Want help with a specific option? Let me know!

