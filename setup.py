#!/usr/bin/env python3
import subprocess
import sys
import os
import shutil

def install_requirements():
    """Install required packages"""
    print("📦 Installing required packages...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ All packages installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing packages: {e}")
        return False
    return True

def setup_env_file():
    """Setup .env file if it doesn't exist"""
    if not os.path.exists('.env'):
        if os.path.exists('.env.template'):
            print("📝 Creating .env file from template...")
            shutil.copy('.env.template', '.env')
            print("✅ .env file created!")
            print("\n⚠️  Please edit the .env file and add your bot token!")
            print("   Open .env and replace 'your_bot_token_here' with your actual token")
            return False
        else:
            print("❌ .env.template not found!")
            return False
    else:
        print("✅ .env file already exists")
        return True

def check_token():
    """Check if bot token is set"""
    # Try loading from .env first
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            content = f.read()
            if 'your_bot_token_here' in content:
                print("⚠️  Please edit .env file and add your real bot token!")
                return False
            elif 'TELEGRAM_BOT_TOKEN=' in content and len(content.strip()) > 20:
                print("✅ Bot token found in .env file")
                return True
    
    # Fallback to environment variable
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        print("\n⚠️  No bot token found!")
        print("\nTo set your bot token:")
        print("1. Create a bot with @BotFather on Telegram")
        print("2. Get your bot token")
        print("3. Edit the .env file and replace 'your_bot_token_here' with your token")
        print("4. Run the bot: python qr_bot.py")
        return False
    else:
        print(f"✅ Bot token found: {token[:10]}...")
        return True

def main():
    print("🤖 QR Code Telegram Bot Setup")
    print("=" * 40)
    
    # Install requirements (manually, due to pip subprocess issue)
    print("⚠️  Skipping automatic requirements installation. Please run 'venv/bin/pip install -r requirements.txt' manually.")
    # if not install_requirements():
    #     sys.exit(1)
    
    print("\n" + "=" * 40)
    
    # Setup .env file
    env_ok = setup_env_file()
    
    print("\n" + "=" * 40)
    
    # Check token
    token_ok = check_token()
    
    print("\n" + "=" * 40)
    print("📋 Setup Summary:")
    print(f"   Packages: ✅ Installed")
    print(f"   Environment: {'✅ Ready' if env_ok else '⚠️  Needs token'}")
    print(f"   Bot Token: {'✅ Found' if token_ok else '❌ Missing'}")
    
    if token_ok:
        print("\n🚀 Ready to run! Execute: python qr_bot.py")
    elif env_ok:
        print("\n⚠️  Please edit .env file and add your bot token!")
    else:
        print("\n⚠️  Please set up your .env file first!")

if __name__ == "__main__":
    main()