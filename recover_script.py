import subprocess

def recover_file(commit, filename, output_path):
    result = subprocess.run(['git', 'show', f'{commit}:{filename}'], capture_output=True)
    content = result.stdout.decode('utf-8', errors='replace')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

recover_file('5ae802e', 'app.js', 'c:/Users/Alegomes/Desktop/Painel gerenciamento/app.js')
