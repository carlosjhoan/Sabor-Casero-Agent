#!/usr/bin/env python3
"""
Setup script for Sabor Casero Assistant
"""
import os
import sys
from pathlib import Path

def setup_project():
    """Setup the project structure"""
    project_root = Path(__file__).parent.parent
    
    print("🚀 Setting up Sabor Casero Assistant...")
    
    # Create necessary directories
    directories = [
        "data/documents",
        "data/templates", 
        "configs",
        "logs",
        "tests"
    ]
    
    for directory in directories:
        path = project_root / directory
        path.mkdir(parents=True, exist_ok=True)
        print(f"  📁 Created: {directory}")
    
    # Create .env file if it doesn't exist
    env_file = project_root / ".env"
    if not env_file.exists():
        with open(env_file, "w") as f:
            f.write("""# DeepSeek API Configuration
DEEPSEEK_API_KEY=your_api_key_here

# Application Settings
ENVIRONMENT=development
LOG_LEVEL=INFO

# Optional: Redis for caching
# REDIS_URL=redis://localhost:6379/0
""")
        print("  📝 Created: .env (edit with your API key)")
    
    # Create default config
    config_file = project_root / "configs" / "development.yaml"
    if not config_file.exists():
        from ..src.utils.config import load_config
        with open(config_file, "w") as f:
            
        print("  ⚙️  Created: configs/development.yaml")
    
    print("\n✅ Setup complete!")
    print("\nNext steps:")
    print("1. Edit .env file with your DeepSeek API key")
    print("2. Add your restaurant documents to data/documents/")
    print("3. Run: python src/main.py --mode cli (to test)")
    print("4. Run: python src/main.py --mode gradio (for GUI)")

if __name__ == "__main__":
    setup_project()