#!/usr/bin/env python3
"""
Recursively generate mdBook API documentation from all PKScreener source code.
This script finds EVERY Python file in pkscreener/ and its subdirectories.
"""

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

class APIDocGenerator:
    """Generate API documentation from Python source code recursively."""
    
    def __init__(self, project_root: Path, book_src: Path):
        self.project_root = project_root
        self.book_src = book_src
        self.api_dir = book_src / "api"
        self.api_dir.mkdir(exist_ok=True)
        
    def find_all_python_files(self, start_path: Path) -> List[Tuple[Path, str]]:
        """
        Recursively find all Python files in pkscreener directory.
        Returns list of (filepath, module_path) tuples.
        """
        python_files = []
        
        # Walk through all subdirectories
        for root, dirs, files in os.walk(start_path):
            # Skip __pycache__ and virtual environment directories
            if '__pycache__' in dirs:
                dirs.remove('__pycache__')
            if '.venv' in dirs:
                dirs.remove('.venv')
            if 'venv' in dirs:
                dirs.remove('venv')
            
            for file in files:
                if file.endswith('.py') and file != '__init__.py':
                    filepath = Path(root) / file
                    
                    # Generate a meaningful module path for documentation
                    rel_path = filepath.relative_to(self.project_root)
                    module_name = str(rel_path).replace('/', '.').replace('\\', '.').replace('.py', '')
                    
                    python_files.append((filepath, module_name))
        
        return python_files
    
    def parse_python_file(self, filepath: Path) -> Dict:
        """Parse a Python file and extract class and function information."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            classes = []
            functions = []
            
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    class_info = self._parse_class(node)
                    classes.append(class_info)
                elif isinstance(node, ast.FunctionDef):
                    if not node.name.startswith('_') or node.name == '__init__':
                        func_info = self._parse_function(node)
                        functions.append(func_info)
            
            return {
                'classes': classes,
                'functions': functions,
                'filepath': str(filepath)
            }
        except Exception as e:
            print(f"  ⚠️ Error parsing {filepath}: {e}")
            return {'classes': [], 'functions': [], 'filepath': str(filepath)}
    
    def _parse_class(self, node: ast.ClassDef) -> Dict:
        """Parse a class definition."""
        methods = []
        class_vars = []
        
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                # Include all methods except deep privates (but keep __init__)
                if not item.name.startswith('_') or item.name == '__init__':
                    methods.append(self._parse_function(item))
            elif isinstance(item, ast.AnnAssign):
                # Class variable with type annotation
                if isinstance(item.target, ast.Name):
                    class_vars.append(item.target.id)
            elif isinstance(item, ast.Assign):
                # Class variable without annotation
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        class_vars.append(target.id)
        
        return {
            'name': node.name,
            'docstring': ast.get_docstring(node) or "",
            'methods': methods,
            'class_vars': class_vars,
            'bases': [self._get_base_name(base) for base in node.bases if isinstance(base, ast.Name)]
        }
    
    def _parse_function(self, node: ast.FunctionDef) -> Dict:
        """Parse a function definition."""
        args = []
        defaults = []
        
        # Collect arguments
        for arg in node.args.args:
            if arg.arg not in ('self', 'cls'):
                args.append(arg.arg)
        
        # Handle default values
        if node.args.defaults:
            for default in node.args.defaults:
                if isinstance(default, ast.Constant):
                    defaults.append(repr(default.value))
                else:
                    defaults.append("...")
        
        # Build argument string with defaults
        args_with_defaults = []
        for i, arg in enumerate(args):
            default_idx = i - (len(args) - len(defaults))
            if default_idx >= 0 and default_idx < len(defaults):
                args_with_defaults.append(f"{arg}={defaults[default_idx]}")
            else:
                args_with_defaults.append(arg)
        
        return {
            'name': node.name,
            'docstring': ast.get_docstring(node) or "",
            'args': args_with_defaults,
            'raw_args': args,
            'is_async': isinstance(node, ast.AsyncFunctionDef)
        }
    
    def _get_base_name(self, node: ast.AST) -> str:
        """Extract base class name."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_base_name(node.value)}.{node.attr}"
        return "Unknown"
    
    def generate_markdown_for_file(self, filepath: Path, module_name: str, parsed_info: Dict) -> str:
        """Generate markdown documentation for a single Python file."""
        # Create a clean title from module name
        title = module_name.replace('pkscreener.', '')
        
        output = f"# `{title}`\n\n"
        output += f"**Source:** `{parsed_info['filepath']}`\n\n"
        
        if parsed_info['classes']:
            output += "## Classes\n\n"
            for cls in parsed_info['classes']:
                output += f"### `{cls['name']}`\n\n"
                
                if cls['docstring']:
                    output += f"{cls['docstring']}\n\n"
                
                if cls.get('bases'):
                    output += f"**Inherits from:** {', '.join(cls['bases'])}\n\n"
                
                if cls.get('class_vars'):
                    output += "**Class Variables:**\n"
                    for var in cls['class_vars']:
                        output += f"- `{var}`\n"
                    output += "\n"
                
                if cls['methods']:
                    output += "#### Methods\n\n"
                    for method in cls['methods']:
                        async_prefix = "async " if method.get('is_async') else ""
                        args_str = ', '.join(method['args'])
                        output += f"##### `{async_prefix}{method['name']}({args_str})`\n\n"
                        
                        if method['docstring']:
                            # Clean up docstring - take first paragraph
                            doc_lines = method['docstring'].strip().split('\n')
                            brief_doc = doc_lines[0]
                            output += f"{brief_doc}\n\n"
                        
                        output += "```python\n"
                        output += f"# Example\n"
                        output += f"# {method['name']}(...)\n"
                        output += "```\n\n"
        
        if parsed_info['functions']:
            output += "## Functions\n\n"
            for func in parsed_info['functions']:
                async_prefix = "async " if func.get('is_async') else ""
                args_str = ', '.join(func['args'])
                output += f"### `{async_prefix}{func['name']}({args_str})`\n\n"
                
                if func['docstring']:
                    doc_lines = func['docstring'].strip().split('\n')
                    brief_doc = doc_lines[0]
                    output += f"{brief_doc}\n\n"
        
        if not parsed_info['classes'] and not parsed_info['functions']:
            output += "*This file contains no classes or public functions.*\n\n"
        
        return output
    
    def generate_navigation_summary(self, all_files: List[Tuple[Path, str, Dict]]) -> str:
        """Generate a navigation-friendly summary of all API modules."""
        # Group by directory
        modules_by_dir = {}
        
        for filepath, module_name, parsed_info in all_files:
            # Get the directory path relative to pkscreener
            rel_path = filepath.relative_to(self.project_root / 'pkscreener')
            dir_name = str(rel_path.parent) if rel_path.parent != Path('.') else 'root'
            
            if dir_name not in modules_by_dir:
                modules_by_dir[dir_name] = []
            
            modules_by_dir[dir_name].append({
                'filepath': filepath,
                'module_name': module_name,
                'parsed_info': parsed_info,
                'display_name': filepath.stem
            })
        
        # Generate summary markdown
        summary = "# API Reference\n\n"
        summary += "Welcome to the PKScreener API Reference. This documentation is automatically generated from the source code.\n\n"
        summary += f"**Last Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        summary += "## Module Index\n\n"
        
        # Sort directories
        for dir_name in sorted(modules_by_dir.keys()):
            if dir_name == 'root':
                summary += "### Root Modules\n\n"
            else:
                summary += f"### `{dir_name}/`\n\n"
            
            for module in sorted(modules_by_dir[dir_name], key=lambda x: x['display_name']):
                # Count classes and functions for display
                class_count = len(module['parsed_info']['classes'])
                func_count = len(module['parsed_info']['functions'])
                
                badge = ""
                if class_count > 0:
                    badge += f" `{class_count} class{'es' if class_count != 1 else ''}`"
                if func_count > 0:
                    badge += f" `{func_count} function{'s' if func_count != 1 else ''}`"
                
                # Create a safe filename from module name
                safe_name = module['module_name'].replace('pkscreener.', '').replace('.', '_')
                summary += f"- [`{module['display_name']}`](api/API_{safe_name}.md){badge}\n"
            
            summary += "\n"
        
        summary += "---\n\n"
        summary += "## File Structure\n\n"
        summary += "The API documentation mirrors the source code structure:\n\n"
        summary += "```\n"
        summary += "pkscreener/\n"
        summary += "├── __init__.py\n"
        summary += "├── globals.py\n"
        summary += "├── pkscreenercli.py\n"
        summary += "├── pkscreenerbot.py\n"
        summary += "├── classes/\n"
        summary += "│   ├── StockScreener.py\n"
        summary += "│   ├── ScreeningStatistics.py\n"
        summary += "│   ├── Fetcher.py\n"
        summary += "│   ├── CandlePatterns.py\n"
        summary += "│   ├── Pktalib.py\n"
        summary += "│   ├── bot/\n"
        summary += "│   │   └── BotHandlers.py\n"
        summary += "│   ├── cli/\n"
        summary += "│   │   └── ...\n"
        summary += "│   └── screening/\n"
        summary += "│       └── ...\n"
        summary += "└── ...\n"
        summary += "```\n"
        
        return summary
    
    def generate_all_docs(self):
        """Recursively generate documentation for all Python files."""
        print("🔍 Scanning for Python files...")
        
        pkscreener_dir = self.project_root / 'pkscreener'
        if not pkscreener_dir.exists():
            print(f"❌ Error: {pkscreener_dir} not found!")
            return
        
        # Find all Python files
        python_files = self.find_all_python_files(pkscreener_dir)
        print(f"📁 Found {len(python_files)} Python files to document\n")
        
        all_modules_info = []
        
        for filepath, module_name in python_files:
            print(f"📄 Processing: {filepath.relative_to(self.project_root)}")
            parsed_info = self.parse_python_file(filepath)
            
            if parsed_info['classes'] or parsed_info['functions']:
                # Generate markdown for this file
                markdown = self.generate_markdown_for_file(filepath, module_name, parsed_info)
                
                # Save to api directory with safe filename
                safe_name = module_name.replace('pkscreener.', '').replace('.', '_')
                output_path = self.api_dir / f"API_{safe_name}.md"
                output_path.write_text(markdown, encoding='utf-8')
                print(f"  ✓ Generated {output_path.name}")
                
                all_modules_info.append((filepath, module_name, parsed_info))
            else:
                print(f"  ⏭️ Skipped (no public classes/functions)")
        
        # Generate the main API reference index
        api_index = self.generate_navigation_summary(all_modules_info)
        (self.book_src / "API_REFERENCE.md").write_text(api_index, encoding='utf-8')
        print(f"\n✅ Generated API_REFERENCE.md")
        
        # Generate an index page for the API directory
        api_index_page = "# API Modules\n\n"
        api_index_page += "This directory contains API documentation for all PKScreener modules.\n\n"
        api_index_page += "## Contents\n\n"
        
        for api_file in sorted(self.api_dir.glob("API_*.md")):
            if api_file.name != "API_INDEX.md":
                api_index_page += f"- [{api_file.stem.replace('API_', '')}]({api_file.name})\n"
        
        (self.api_dir / "INDEX.md").write_text(api_index_page, encoding='utf-8')
        
        print(f"\n✨ API documentation complete!")
        print(f"📊 Documented {len(all_modules_info)} modules with public APIs")

def main():
    project_root = Path.cwd()
    
    # Find the book source directory
    book_src_candidates = [
        project_root / "docs" / "docs" / "book" / "src",
        project_root / "docs" / "book" / "src",
    ]
    
    book_src = None
    for candidate in book_src_candidates:
        if candidate.exists() or candidate.parent.exists():
            book_src = candidate
            break
    
    if book_src is None:
        print("❌ Error: Could not find mdBook src directory")
        print("Please ensure you're running this from the project root")
        sys.exit(1)
    
    print(f"📚 Book source directory: {book_src}")
    print(f"🐍 Project root: {project_root}")
    print()
    
    generator = APIDocGenerator(project_root, book_src)
    generator.generate_all_docs()

if __name__ == "__main__":
    main()