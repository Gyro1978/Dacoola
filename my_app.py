import modal

app = modal.App("my-first-modal-app")

@app.function()
def my_function(name):
    print(f"Hello, {name} from Modal!")
    return f"Greetings, {name}!"

@app.local_entrypoint()
def main():
    # Run the function remotely on Modal
    result = my_function.remote("World")
    print(result)