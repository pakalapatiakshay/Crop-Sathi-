import os

def replace_in_file(filepath, replacements):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    modified = False
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            modified = True
            
    if modified:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Updated {filepath}')

replacements = [
    ('AgriSense AI', 'Crop Sathi'),
    ('AgriSense', 'Crop Sathi'),
    ('agrisense.ai', 'cropsathi.in'),
    ('agrisense-theme', 'cropsathi-theme'),
    ('Namaste, Arshad', 'Namaste, Kisan'),
    ('<div class="avatar">RK</div>', '<div class="avatar">K</div>'),
    ('["English", "हिन्दी", "தமிழ்", "తెలుగు", "मराठी"]', '["English", "Santhali", "Bengali", "Bhashini API (Soon)"]')
]

for root, _, files in os.walk('frontend'):
    for file in files:
        if file.endswith(('.js', '.html', '.css', '.json')):
            path = os.path.join(root, file)
            replace_in_file(path, replacements)
print('Done!')
