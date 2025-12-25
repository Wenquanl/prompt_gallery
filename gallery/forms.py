from django import forms
from .models import PromptGroup, Tag, AIModel

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class MultipleFileField(forms.FileField):
    def to_python(self, data):
        if not data: return None
        if isinstance(data, list): return data
        return [data]
    def validate(self, value):
        if self.required and not value:
            raise forms.ValidationError(self.error_messages['required'], code='required')

class PromptGroupForm(forms.ModelForm):
    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(), widget=forms.CheckboxSelectMultiple, required=False, label="关联标签"
    )
    model_info = forms.ModelChoiceField(
        queryset=AIModel.objects.all(), widget=forms.RadioSelect, label="生成模型", empty_label=None, required=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        model_names = AIModel.objects.values_list('name', flat=True)
        self.fields['tags'].queryset = Tag.objects.exclude(name__in=model_names)
        
        # 强制清空初始值，只显示placeholder
        self.fields['title'].initial = None

    class Meta:
        model = PromptGroup
        # 【修改】添加了 prompt_text_zh 到 fields 列表
        fields = ['title', 'prompt_text', 'prompt_text_zh', 'negative_prompt', 'model_info', 'tags']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': '给这组作品起个标题',
                'list': 'title_list',  # 必须与 HTML 中的 datalist ID 一致
                'autocomplete': 'off'
            }),
            'prompt_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': '输入正向提示词...'}),
            # 【新增】中文/辅助提示词的控件配置
            'prompt_text_zh': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': '输入中文或辅助提示词 (可选)...'}),
            'negative_prompt': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': '输入负向提示词 (可选)...'}),
        }

    # 生成图上传
    upload_images = MultipleFileField(
        widget=MultipleFileInput(attrs={'multiple': True, 'class': 'form-control'}),
        label="批量上传生成图", required=True, help_text="支持批量选择 (必须)"
    )

    # 参考图上传
    upload_references = MultipleFileField(
        widget=MultipleFileInput(attrs={'multiple': True, 'class': 'form-control'}),
        label="批量上传参考图", required=False, help_text="支持批量选择 (可选)"
    )

    def clean_upload_images(self):
        return self.files.getlist('upload_images')
    
    def clean_upload_references(self):
        return self.files.getlist('upload_references')