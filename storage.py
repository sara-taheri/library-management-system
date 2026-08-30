import json
import json

def load_data(filename):
    
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        return []
    

def save_data(filename, data):
   
    with open(filename, 'w') as f:
        json.dump(data, f)
