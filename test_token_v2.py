#!/usr/bin/env python3
"""
Quick test script to verify AccessToken2 (v007) token generation.
Run this after deploying to verify tokens start with "007" instead of "006".
"""
import os
import sys
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from apps.consultations.agora_service import AgoraService

def test_token_generation():
    """Generate a test token and verify it starts with 007."""
    print("=" * 60)
    print("Testing AccessToken2 (v007) Generation")
    print("=" * 60)
    
    # Test parameters
    channel_name = "test_channel_v2"
    uid = 12345
    
    try:
        token = AgoraService.generate_rtc_token(
            channel_name=channel_name,
            uid=uid,
            expire_seconds=3600
        )
        
        token_version = token[:3]
        token_prefix = token[:10]
        
        print(f"\n✓ Token generated successfully")
        print(f"  Version prefix: {token_version}")
        print(f"  Token preview: {token_prefix}...")
        print(f"  Full length: {len(token)} characters")
        
        if token_version == "007":
            print(f"\n✓ SUCCESS: Token uses AccessToken2 (v007)")
            print(f"  This token is compatible with Agora SDK 6.x")
            return True
        elif token_version == "006":
            print(f"\n✗ ERROR: Token still uses AccessToken v1 (v006)")
            print(f"  This indicates the import didn't switch to AccessToken2")
            return False
        else:
            print(f"\n✗ WARNING: Unexpected token version: {token_version}")
            return False
            
    except Exception as e:
        print(f"\n✗ ERROR: Token generation failed")
        print(f"  {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_token_generation()
    print("\n" + "=" * 60)
    sys.exit(0 if success else 1)
