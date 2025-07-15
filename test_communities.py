#!/usr/bin/env python3
"""
Test script for WhatsApp Communities compatibility checking
"""

import sys
import os

# Add the MCP server to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'whatsapp-mcp-server'))

from main import check_group_compatibility

def test_group_compatibility():
    """Test the group compatibility checking function"""
    
    test_cases = [
        # Personal chat
        "6590044236@s.whatsapp.net",
        
        # Traditional group  
        "6585330654-1415953791@g.us",
        
        # WhatsApp Community (problematic)
        "120363383015042404@g.us",
        
        # Community member with @lid (not supported)
        "6590044236@lid",
        
        # Unknown format
        "test@unknown.com",
    ]
    
    print("🧪 Testing WhatsApp Group Compatibility Checker\n")
    
    for jid in test_cases:
        print(f"Testing JID: {jid}")
        result = check_group_compatibility(jid)
        print(f"  Type: {result['type']}")
        print(f"  Compatible: {'✅' if result['compatible'] else '❌'}")
        print(f"  Description: {result['description']}")
        print(f"  Recommendations:")
        for rec in result['recommendations']:
            print(f"    - {rec}")
        print()

if __name__ == "__main__":
    test_group_compatibility() 