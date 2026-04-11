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
    pass


class SourceRootUpdateForm(SourceRootForm):
    pass