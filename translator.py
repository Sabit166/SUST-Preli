translation_prompt = """
You are a translator. The input may be in Bangla, Banglish (Bangla written in English letters), 
or mixed Bangla-English. 

Translate it to clear English. If it is already in English, return it as-is.
Return ONLY the translated text, nothing else.

Input: {complaint}
"""

# Step 2: Feed the translated complaint into your main agent