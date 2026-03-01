from django import forms
from django.db.models import Count, Case, When, IntegerField
from django.db.models.functions import Lower
from .models import PromptGroup, Tag, AIModel, Character

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
    characters = forms.ModelMultipleChoiceField(
        queryset=Character.objects.all(), 
        widget=forms.CheckboxSelectMultiple, 
        required=False, 
        label="包含人物"
    )
    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(), widget=forms.CheckboxSelectMultiple, required=False, label="关联标签"
    )
    model_info = forms.ModelChoiceField(
        queryset=AIModel.objects.all(), widget=forms.RadioSelect, label="生成模型", empty_label=None, required=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # === 1. 对关联标签 (Tags) 进行排序 ===
        model_names = AIModel.objects.values_list('name', flat=True)
        
        # 【修正】根据错误提示，反向关联字段名为 'promptgroup' 而非 'promptgroup_set'
        self.fields['tags'].queryset = Tag.objects.exclude(
            name__in=model_names
        ).annotate(
            usage_count=Count('promptgroup')
        ).order_by('-usage_count', 'name')
        
        # === 2. 对生成模型 (AIModel) 进行排序 ===
        # 统计 PromptGroup 表中各字符串的使用次数
        # 使用 Lower() 忽略大小写进行统计，提高匹配率
        model_usage_stats = dict(
            PromptGroup.objects.annotate(
                model_lower=Lower('model_info')
            ).values_list('model_lower').annotate(cnt=Count('id')).values_list('model_lower', 'cnt')
        )
        
        # 构建 Case/When 表达式
        whens = []
        all_models = AIModel.objects.all()
        for m in all_models:
            # 同样将 AIModel 的名称转为小写去匹配统计结果
            count = model_usage_stats.get(str(m.name).lower(), 0)
            if count > 0:
                whens.append(When(pk=m.pk, then=count))

        # 应用排序：优先按计算出的使用量降序，其次按 order 权重降序
        if whens:
            self.fields['model_info'].queryset = AIModel.objects.annotate(
                calculated_usage=Case(
                    *whens,
                    default=0,
                    output_field=IntegerField()
                )
            ).order_by('-calculated_usage', '-order', 'name')
        else:
            # 如果没有任何匹配数据，按默认权重排序
            self.fields['model_info'].queryset = AIModel.objects.order_by('-order', 'name')

        self.fields['title'].initial = None

    def clean_model_info(self):
        """
        关键修正：确保保存到数据库的是模型的【名称字符串】，而不是模型对象。
        ModelChoiceField 清洗后是对象，但数据库 CharField 需要字符串。
        """
        data = self.cleaned_data['model_info']
        if hasattr(data, 'name'):
            return data.name
        return str(data)

    class Meta:
        model = PromptGroup
        fields = ['title', 'prompt_text', 'prompt_text_zh', 'negative_prompt', 'model_info', 'characters','tags']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': '给这组作品起个标题',
                'list': 'title_list',
                'autocomplete': 'off'
            }),
            'prompt_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': '输入正向提示词...'}),
            'prompt_text_zh': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': '输入中文或辅助提示词 (可选)...'}),
            'negative_prompt': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': '输入负向提示词 (可选)...'}),
        }

    # 生成图上传
    upload_images = MultipleFileField(
        widget=MultipleFileInput(attrs={
            'multiple': True, 
            'class': 'form-control',
            'accept': 'image/*,video/*'
        }),
        label="批量上传生成图/视频", required=True, help_text="支持图片及视频 (必须)"
    )

    # 参考图上传
    upload_references = MultipleFileField(
        widget=MultipleFileInput(attrs={
            'multiple': True, 
            'class': 'form-control',
            'accept': 'image/*,video/*'
        }),
        label="批量上传参考图/视频", required=False, help_text="支持图片及视频 (可选)"
    )

    def clean_upload_images(self):
        return self.files.getlist('upload_images')
    
    def clean_upload_references(self):
        return self.files.getlist('upload_references')