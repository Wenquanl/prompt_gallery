from pathlib import Path

from django import forms


class SourceRootForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        required=False,
        label='资源源名称',
    )
    root_path = forms.CharField(
        max_length=1000,
        label='本地目录路径',
    )
    is_enabled = forms.BooleanField(
        required=False,
        initial=True,
        label='加入后启用同步',
    )

    def clean_root_path(self):
        raw_path = (self.cleaned_data.get('root_path') or '').strip()
        if not raw_path:
            raise forms.ValidationError('请输入本地目录路径。')

        resolved_path = Path(raw_path).expanduser().resolve()
        if not resolved_path.exists() or not resolved_path.is_dir():
            raise forms.ValidationError('目录不存在，或不是可扫描的文件夹。')
        return str(resolved_path)

    def clean_name(self):
        return (self.cleaned_data.get('name') or '').strip()


class SourceRootCreateForm(SourceRootForm):
    root_path = forms.CharField(
        max_length=5000,
        label='本地目录路径',
        widget=forms.Textarea(attrs={'rows': 4}),
    )

    def clean_root_path(self):
        raw_path = (self.cleaned_data.get('root_path') or '').strip()
        if not raw_path:
            raise forms.ValidationError('请输入至少一个本地目录路径。')
        return raw_path

    def clean(self):
        cleaned_data = super().clean()
        raw_path = cleaned_data.get('root_path') or ''
        source_name = (cleaned_data.get('name') or '').strip()
        raw_lines = [line.strip() for line in raw_path.splitlines() if line.strip()]
        if not raw_lines:
            self.add_error('root_path', '请输入至少一个本地目录路径。')
            return cleaned_data

        resolved_paths = []
        seen_paths = set()
        for raw_line in raw_lines:
            resolved_path = Path(raw_line).expanduser().resolve()
            if not resolved_path.exists() or not resolved_path.is_dir():
                self.add_error('root_path', f'目录不存在，或不是可扫描的文件夹：{raw_line}')
                return cleaned_data

            normalized_path = str(resolved_path)
            if normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            resolved_paths.append(normalized_path)

        if len(resolved_paths) > 1 and source_name:
            self.add_error('name', '批量添加多个目录时，请留空显示名称，系统会按目录名自动生成。')

        cleaned_data['root_paths'] = resolved_paths
        cleaned_data['root_path'] = '\n'.join(resolved_paths)
        return cleaned_data


class SourceRootUpdateForm(SourceRootForm):
    pass