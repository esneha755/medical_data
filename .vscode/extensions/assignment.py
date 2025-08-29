# Program to read and write to a binary file using random access

# Create a binary file and write data
with open("example.bin", "wb") as file:
    # Writing data to the binary file
    file.write(b"Hello, this is a binary file example.")

# Read and write using random access
with open("example.bin", "r+b") as file:
    # Move the file pointer to the 18th byte (index 17)
    file.seek(17)  
    # Overwrite a part of the data
    file.write(b"modified content")
    
    # Move the pointer back to the beginning
    file.seek(0)
    # Read the updated content
    updated_content = file.read()

# Display the updated content
print("Updated file content:", updated_content.decode('utf-8'))
