from pathlib import Path

# Danh sách các thư mục/file muốn bỏ qua (như git, cache,...)
IGNORED_NAMES = {".git", "__pycache__", ".venv", "node_modules", ".DS_Store", "ascii_tree_generator.py"}

# Danh sách các đuôi file (extension) muốn bỏ qua
IGNORED_EXTENSIONS = {".class", ".pyc", ".bat"}

def generate_ascii_tree(dir_path: Path, prefix: str = "") -> str:
    """Hàm đệ quy để tạo chuỗi ASCII tree."""
    tree_str = ""
    
    # Lọc bỏ các file/thư mục nằm trong IGNORED_NAMES hoặc có đuôi thuộc IGNORED_EXTENSIONS
    contents = [
        p for p in dir_path.iterdir()
        if p.name not in IGNORED_NAMES and p.suffix.lower() not in IGNORED_EXTENSIONS
    ]
    
    # Sắp xếp: Thư mục lên trước, file theo sau (theo thứ tự alphabet)
    contents.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
    
    count = len(contents)
    for index, path in enumerate(contents):
        is_last = (index == count - 1)
        connector = "└── " if is_last else "├── "
        
        tree_str += f"{prefix}{connector}{path.name}\n"
        
        # Nếu là thư mục, tiếp tục đệ quy quét các file bên trong
        if path.is_dir():
            extension = "    " if is_last else "│   "
            tree_str += generate_ascii_tree(path, prefix + extension)
            
    return tree_str

def save_project_tree(project_dir: str, output_file: str):
    """Quét dự án và lưu cấu trúc vào file text."""
    root_path = Path(project_dir)
    if not root_path.exists() or not root_path.is_dir():
        print(f"Lỗi: Thư mục '{project_dir}' không tồn tại!")
        return

    # Tạo nội dung cây
    tree_content = f"{root_path.resolve().name}/\n"
    tree_content += generate_ascii_tree(root_path)

    # Lưu nội dung ra file text (dùng utf-8 để không bị lỗi font ASCII)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(tree_content)

    print(f"Đã xuất cây thư mục thành công vào file: {output_file}")

# --- Cách sử dụng ---
if __name__ == "__main__":
    PROJECT_PATH = "."       # Đường dẫn thư mục dự án ('.' là thư mục hiện tại)
    OUTPUT_FILE = "project_structure.txt" # Tên file text xuất ra
    
    save_project_tree(PROJECT_PATH, OUTPUT_FILE)