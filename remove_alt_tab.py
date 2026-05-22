# -*- coding: utf-8 -*-
"""
修复：删除残留的 Alt+Tab 代码
"""

with open(r'c:\Users\Administrator\.trae-cn\work\6a0ab63a2bcdb6229cdc327a\clipboard\smart_clipboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修复1: paste_content - 删除 Alt+Tab 代码
old1 = '''            # 远程桌面环境：切换焦点强制剪贴板同步
            # Alt+Tab 出去再回来，确保回到原窗口
            with keyboard.pressed(Key.alt):
                keyboard.tap(Key.tab)
            time.sleep(0.2)  # 等待剪贴板同步
            with keyboard.pressed(Key.alt):
                keyboard.tap(Key.tab)
            time.sleep(0.1)  # 等待回到原窗口
            
            # 确保 Alt 键已释放'''

new1 = '''            # 确保 Alt 键已释放'''

if old1 in content:
    content = content.replace(old1, new1)
    print("✓ 修复1完成: paste_content 删除 Alt+Tab 代码")
else:
    print("✗ 修复1失败")

# 修复2: PinnedItemWindow._do_paste - 删除 Alt+Tab 代码
old2 = '''                # 远程桌面环境：切换焦点强制剪贴板同步
                # Alt+Tab 出去再回来
                with PinnedItemWindow._keyboard.pressed(Key.alt):
                    PinnedItemWindow._keyboard.tap(Key.tab)
                time.sleep(0.2)
                with PinnedItemWindow._keyboard.pressed(Key.alt):
                    PinnedItemWindow._keyboard.tap(Key.tab)
                time.sleep(0.1)
                
                # 确保 Alt 键已释放'''

new2 = '''                # 确保 Alt 键已释放'''

if old2 in content:
    content = content.replace(old2, new2)
    print("✓ 修复2完成: PinnedItemWindow._do_paste 删除 Alt+Tab 代码")
else:
    print("✗ 修复2失败")

# 保存
with open(r'c:\Users\Administrator\.trae-cn\work\6a0ab63a2bcdb6229cdc327a\clipboard\smart_clipboard.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\n修复完成！Alt+Tab 代码已删除。")
