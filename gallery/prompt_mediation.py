import re


OPTIMIZATION_LEVEL_OFF = 'off'
OPTIMIZATION_LEVEL_CONSERVATIVE = 'conservative'
OPTIMIZATION_LEVEL_BALANCED = 'balanced'
OPTIMIZATION_LEVEL_ENHANCED = 'enhanced'
OPTIMIZATION_LEVEL_VISUAL_REWRITE = 'visual_rewrite'
OPTIMIZATION_LEVEL_ALIASES = {
    OPTIMIZATION_LEVEL_CONSERVATIVE: OPTIMIZATION_LEVEL_BALANCED,
    OPTIMIZATION_LEVEL_VISUAL_REWRITE: OPTIMIZATION_LEVEL_ENHANCED,
    'faithful': OPTIMIZATION_LEVEL_BALANCED,
}
OPTIMIZATION_LEVEL_ORDER = {
    OPTIMIZATION_LEVEL_OFF: 0,
    OPTIMIZATION_LEVEL_BALANCED: 1,
    OPTIMIZATION_LEVEL_ENHANCED: 2,
}

CONTROL_SEGMENT_LABELS = {
    '比例',
    '画幅',
    '画幅比例',
    '构图比例',
    '纵横比',
    '尺寸',
    '分辨率',
    '负面',
    '负面提示',
    '负面约束',
    '约束',
    '限制',
    '保留',
    '锁定',
    'negative',
    'negative prompt',
    'negative constraints',
    'constraints',
    'preserve',
}

CONTROL_SEGMENT_PATTERN = re.compile(
    r'不要改|不要改变|保持不变|保留|锁定|preserve|keep\b|do not change|don\'t change|without changing|negative prompt|negative constraints',
    re.IGNORECASE,
)

RATIO_PATTERN = re.compile(r'\b\d+\s*:\s*\d+\b|aspect\s*ratio', re.IGNORECASE)


PROMPT_REWRITE_RULES = [
    {
        'pattern': re.compile(r'手指停留在下唇前方极近的位置\s*[\(（]?(?:几乎接触但不触碰)?[\)）]?', re.IGNORECASE),
        'replacement': 'finger gently posed near lips, relaxed and natural',
        'replacement_by_level': {
            OPTIMIZATION_LEVEL_ENHANCED: 'relaxed hand gesture near face, clean editorial pose',
        },
        'reason_tag': '弱化动作边界',
        'reason': '将强动作边界改写为更自然的视觉描述',
        'category': 'pose',
        'min_level': OPTIMIZATION_LEVEL_BALANCED,
    },
    {
        'pattern': re.compile(r'指尖轻触下唇|指尖轻触嘴唇|手指轻触下唇|手指轻触嘴唇|finger(?:tips?)?\s+(?:lightly\s+)?touching\s+lips?', re.IGNORECASE),
        'replacement': 'hand posed near lips naturally',
        'replacement_by_level': {
            OPTIMIZATION_LEVEL_ENHANCED: 'relaxed hand gesture near face',
        },
        'reason_tag': '弱化动作边界',
        'reason': '将直接口部接触改写为更中性的手部姿态描述',
        'category': 'pose',
        'min_level': OPTIMIZATION_LEVEL_BALANCED,
    },
    {
        'pattern': re.compile(r'几乎接触但不触碰|几乎接触|接近嘴唇|靠近嘴唇|贴近嘴唇', re.IGNORECASE),
        'replacement': 'near lips naturally',
        'replacement_by_level': {
            OPTIMIZATION_LEVEL_ENHANCED: 'near face naturally',
        },
        'reason_tag': '弱化动作边界',
        'reason': '弱化接触边界，减少强控制表达',
        'category': 'pose',
        'min_level': OPTIMIZATION_LEVEL_CONSERVATIVE,
    },
    {
        'pattern': re.compile(r'轻咬下唇|咬唇|含唇|舔唇|舌尖轻抵嘴唇|tongue(?:\s+tip)?\s+(?:touching|against)\s+lips?', re.IGNORECASE),
        'replacement': 'soft natural lip expression',
        'reason_tag': '口部动作中性化',
        'reason': '将带有明显暗示的口部动作改写为更自然的神态描述',
        'category': 'expression',
        'min_level': OPTIMIZATION_LEVEL_ENHANCED,
    },
    {
        'pattern': re.compile(r'轻微暧昧氛围|暧昧氛围|轻微暧昧|暧昧', re.IGNORECASE),
        'replacement': 'subtle cinematic mood',
        'replacement_by_level': {
            OPTIMIZATION_LEVEL_ENHANCED: 'stylized editorial atmosphere',
        },
        'reason_tag': '情绪抽象化',
        'reason': '将情绪暗示改写为中性氛围词',
        'category': 'mood',
        'min_level': OPTIMIZATION_LEVEL_CONSERVATIVE,
    },
    {
        'pattern': re.compile(r'迷离眼神|眼神迷离|魅惑眼神|勾人眼神|撩人眼神', re.IGNORECASE),
        'replacement': 'calm confident gaze',
        'reason_tag': '神态中性化',
        'reason': '将过强的眼神暗示改写为更中性的气质表达',
        'category': 'expression',
        'min_level': OPTIMIZATION_LEVEL_ENHANCED,
    },
    {
        'pattern': re.compile(r'欲望感|欲感|性张力', re.IGNORECASE),
        'replacement': 'stylized cinematic tension',
        'reason_tag': '情绪抽象化',
        'reason': '将直接欲望导向改写为更通用的影像氛围描述',
        'category': 'mood',
        'min_level': OPTIMIZATION_LEVEL_ENHANCED,
    },
    {
        'pattern': re.compile(r'呼吸感|喘息感|breathless', re.IGNORECASE),
        'replacement': 'calm relaxed expression',
        'reason_tag': '身体状态降级',
        'reason': '移除高风险身体状态描述',
        'category': 'expression',
        'min_level': OPTIMIZATION_LEVEL_CONSERVATIVE,
    },
    {
        'pattern': re.compile(r'湿身|汗湿发丝|汗湿肌肤|汗珠滑过肌肤|肌肤泛着湿光|油亮肌肤', re.IGNORECASE),
        'replacement': 'dewy skin texture',
        'reason_tag': '外观质感中性化',
        'reason': '将带有强身体联想的表面质感改写为更常规的外观描述',
        'category': 'appearance',
        'min_level': OPTIMIZATION_LEVEL_ENHANCED,
    },
    {
        'pattern': re.compile(r'湿润嘴唇|湿润的嘴唇|wet lips|moist lips', re.IGNORECASE),
        'replacement': 'soft glossy lips',
        'replacement_by_level': {
            OPTIMIZATION_LEVEL_ENHANCED: 'natural lip detail',
        },
        'reason_tag': '外观质感中性化',
        'reason': '改成更常规的外观质感描述',
        'category': 'appearance',
        'min_level': OPTIMIZATION_LEVEL_CONSERVATIVE,
    },
    {
        'pattern': re.compile(r'诱惑感|诱惑|挑逗感|seductive|suggestive', re.IGNORECASE),
        'replacement': 'elegant and confident',
        'reason_tag': '情绪抽象化',
        'reason': '将情绪导向改为更中性的气质表达',
        'category': 'mood',
        'min_level': OPTIMIZATION_LEVEL_ENHANCED,
    },
    {
        'pattern': re.compile(r'黑色\s*cutout\s*连体衣|black\s+cutout\s+bodysuit', re.IGNORECASE),
        'replacement': 'sleek black halter outfit',
        'reason_tag': '服装风格化',
        'reason': '将服装结构词改写为更风格化的衣着描述',
        'category': 'wardrobe',
        'min_level': OPTIMIZATION_LEVEL_ENHANCED,
    },
    {
        'pattern': re.compile(r'裸露感|裸露', re.IGNORECASE),
        'replacement': 'minimalist styling',
        'replacement_by_level': {
            OPTIMIZATION_LEVEL_ENHANCED: 'refined editorial styling',
        },
        'reason_tag': '服装风格化',
        'reason': '将直白暴露描述改写为风格表达',
        'category': 'wardrobe',
        'min_level': OPTIMIZATION_LEVEL_CONSERVATIVE,
    },
    {
        'pattern': re.compile(r'深V|低胸|胸前镂空|高开叉|透视薄纱|透视装|透视材质|半透明薄纱|半透明面料', re.IGNORECASE),
        'replacement': 'tailored elegant styling',
        'reason_tag': '服装风格化',
        'reason': '将高暴露度服装细节改写为更概括的着装风格描述',
        'category': 'wardrobe',
        'min_level': OPTIMIZATION_LEVEL_ENHANCED,
    },
    {
        'pattern': re.compile(r'紧身', re.IGNORECASE),
        'replacement': 'fitted',
        'reason_tag': '服装风格化',
        'reason': '将服装贴合度改写为中性版型描述',
        'category': 'wardrobe',
        'min_level': OPTIMIZATION_LEVEL_ENHANCED,
    },
]

STRUCTURED_LABEL_CATEGORY_MAP = {
    '皮肤': 'appearance',
    '肤质': 'appearance',
    '面部': 'appearance',
    '五官': 'appearance',
    '嘴唇': 'appearance',
    '头发': 'appearance',
    '发型': 'appearance',
    '动作': 'pose',
    '姿势': 'pose',
    '手势': 'pose',
    '服装': 'wardrobe',
    '穿搭': 'wardrobe',
    '材质': 'material',
    '灯光': 'lighting',
    '光线': 'lighting',
    '环境': 'environment',
    '背景': 'environment',
    '氛围': 'mood',
    '情绪': 'mood',
    '镜头': 'camera',
    '构图': 'camera',
    '比例': 'layout',
    '画幅': 'layout',
    '画幅比例': 'layout',
    '构图比例': 'layout',
    '纵横比': 'layout',
    '风格': 'style',
    '画质': 'quality',
    '尺寸': 'quality',
    '分辨率': 'quality',
    '负面': 'constraint',
    '负面提示': 'constraint',
    '负面约束': 'constraint',
    '约束': 'constraint',
    '限制': 'constraint',
    '保留': 'constraint',
    '锁定': 'constraint',
}

STRUCTURED_CATEGORY_LABELS = {
    'subject': '主体',
    'appearance': '外观',
    'expression': '神态',
    'pose': '动作',
    'wardrobe': '服装',
    'material': '材质',
    'lighting': '光线',
    'environment': '环境',
    'mood': '氛围',
    'camera': '镜头',
    'layout': '比例',
    'style': '风格',
    'quality': '画质',
    'constraint': '约束',
    'other': '其他',
}

STRUCTURED_PROMPT_ORDER = [
    'camera',
    'layout',
    'subject',
    'appearance',
    'expression',
    'pose',
    'wardrobe',
    'material',
    'environment',
    'lighting',
    'mood',
    'style',
    'quality',
    'constraint',
    'other',
]

STRUCTURED_CATEGORY_ITEM_LIMITS = {
    'camera': 1,
    'layout': 2,
    'subject': 1,
    'appearance': 2,
    'expression': 1,
    'pose': 1,
    'wardrobe': 1,
    'material': 1,
    'environment': 1,
    'lighting': 1,
    'mood': 1,
    'style': 1,
    'quality': 1,
    'constraint': 3,
    'other': 1,
}


def _normalize_label_name(label):
    return str(label or '').strip().lower()


def _is_control_segment_label(label):
    return _normalize_label_name(label) in {item.lower() for item in CONTROL_SEGMENT_LABELS}


def _is_control_segment(label, text):
    normalized_text = str(text or '').strip()
    if _is_control_segment_label(label):
        return True
    if CONTROL_SEGMENT_PATTERN.search(normalized_text):
        return True
    return bool(RATIO_PATTERN.search(normalized_text) and label)


def _should_keep_line_intact(line):
    raw_line = str(line or '').strip()
    if not raw_line:
        return False
    label, content = _extract_structured_label(raw_line)
    return _is_control_segment(label, content)


def _format_segment_output(label, text):
    content = str(text or '').strip()
    clean_label = str(label or '').strip()
    if not content:
        return ''
    if _is_control_segment(clean_label, content):
        return f'{clean_label}：{content}' if clean_label else content
    return content


def _extract_structured_label(segment):
    match = re.match(r'^([A-Za-z0-9_\-/\u4e00-\u9fff ]{1,18})\s*[：:]\s*(.+)$', segment)
    if not match:
        return '', segment.strip()

    label, content = match.groups()
    if len(label.split()) <= 3:
        return label.strip(), content.strip()
    return '', segment.strip()


def _infer_segment_category(label, text):
    normalized_label = str(label or '').strip().lower()
    if normalized_label:
        for source_label, category in STRUCTURED_LABEL_CATEGORY_MAP.items():
            if normalized_label == source_label.lower():
                return category

    if RATIO_PATTERN.search(str(text or '')):
        return 'layout'
    if CONTROL_SEGMENT_PATTERN.search(str(text or '')):
        return 'constraint'

    normalized_text = str(text or '').lower()
    keyword_map = {
        'appearance': ['skin', 'lips', 'hair', 'glass skin', 'glossy'],
        'pose': ['pose', 'hand', 'finger', 'near lips'],
        'wardrobe': ['outfit', 'dress', 'clothing', 'halter', 'fitted'],
        'lighting': ['light', 'flash', 'shadow', 'rim light'],
        'environment': ['background', 'indoor', 'outdoor', 'environment'],
        'mood': ['mood', 'cinematic', 'atmosphere'],
        'camera': ['selfie', 'low-angle', 'portrait', 'close-up'],
        'style': ['style', 'ultra detailed', 'photorealistic'],
        'expression': ['expression', 'calm', 'relaxed'],
    }
    for category, keywords in keyword_map.items():
        if any(keyword in normalized_text for keyword in keywords):
            return category
    return 'other'


def _normalize_optimization_level(value):
    normalized = str(value or '').strip().lower()
    normalized = OPTIMIZATION_LEVEL_ALIASES.get(normalized, normalized)
    if normalized in OPTIMIZATION_LEVEL_ORDER:
        return normalized
    return OPTIMIZATION_LEVEL_BALANCED


def _should_apply_rule(rule, optimization_level):
    required_level = _normalize_optimization_level(rule.get('min_level'))
    return OPTIMIZATION_LEVEL_ORDER[_normalize_optimization_level(optimization_level)] >= OPTIMIZATION_LEVEL_ORDER[required_level]


def _resolve_rule_replacement(rule, optimization_level):
    normalized_level = _normalize_optimization_level(optimization_level)
    replacement_by_level = rule.get('replacement_by_level') or {}
    if normalized_level in replacement_by_level:
        return replacement_by_level[normalized_level]
    return rule['replacement']


def _apply_rules_to_text(text, optimization_level, label=''):
    current_text = str(text or '')
    applied_rules = []
    rewrite_details = []

    for rule in PROMPT_REWRITE_RULES:
        if not _should_apply_rule(rule, optimization_level):
            continue

        pattern = rule['pattern']
        if pattern.search(current_text):
            before_text = current_text
            replacement = _resolve_rule_replacement(rule, optimization_level)
            current_text = pattern.sub(replacement, current_text)
            if current_text == before_text:
                continue

            before_display = f'{label}: {before_text}' if label else before_text
            after_display = f'{label}: {current_text}' if label else current_text
            applied_rules.append(replacement)
            rewrite_details.append({
                'before': before_display,
                'after': after_display,
                'reason_tag': rule.get('reason_tag', ''),
                'reason': rule['reason'],
                'category': rule['category'],
            })

    return current_text, applied_rules, rewrite_details


def _normalize_segment(segment, optimization_level):
    raw_segment = str(segment or '').strip()
    normalized = raw_segment
    if not normalized:
        return None

    normalized = normalized.replace('（', '(').replace('）', ')')
    normalized = normalized.replace('，', ',')
    normalized = re.sub(r'[\{\}\[\]"]+', ' ', normalized)
    normalized = re.sub(r'^[\-•*\d\.)\s]+', '', normalized)
    label, normalized = _extract_structured_label(normalized)

    if _is_control_segment(label, normalized):
        current_text = normalized
        applied_rules = []
        rewrite_details = []
    else:
        current_text, applied_rules, rewrite_details = _apply_rules_to_text(
            normalized,
            optimization_level,
            label=label,
        )

    current_text = re.sub(r'\s+', ' ', current_text)
    current_text = re.sub(r'\s*,\s*', ', ', current_text)
    current_text = current_text.strip(' ,')

    category = _infer_segment_category(label, current_text)
    output_text = _format_segment_output(label, current_text)
    return {
        'label': label,
        'category': category,
        'original_text': raw_segment,
        'normalized_text': normalized,
        'optimized_text': current_text,
        'output_text': output_text,
        'changed': current_text != normalized or bool(label),
        'applied_rules': applied_rules,
        'rewrite_details': rewrite_details,
    }


def _build_structured_outline(segments):
    grouped = {}
    for category in STRUCTURED_PROMPT_ORDER:
        grouped[category] = []

    for segment in segments:
        category = segment['category'] if segment['category'] in grouped else 'other'
        text = segment['optimized_text']
        if text and text not in grouped[category]:
            grouped[category].append(text)

    outline = []
    for category in STRUCTURED_PROMPT_ORDER:
        items = grouped.get(category) or []
        if not items:
            continue
        outline.append({
            'category': category,
            'label': STRUCTURED_CATEGORY_LABELS.get(category, category),
            'items': items,
        })
    return outline


def _build_short_visual_prompt(structured_outline):
    selected_parts = []
    for block in structured_outline:
        if not block['items']:
            continue
        item_limit = STRUCTURED_CATEGORY_ITEM_LIMITS.get(block['category'], 1)
        selected_parts.extend(block['items'][:item_limit])
        if len(selected_parts) >= 12:
            selected_parts = selected_parts[:12]
            break

    short_prompt = ', '.join(selected_parts)
    short_prompt = re.sub(r'\s+', ' ', short_prompt).strip(' ,')
    return short_prompt


def _build_flattened_prompt(segments):
    flattened_parts = []
    for segment in segments:
        output_text = segment.get('output_text') or segment['optimized_text']
        if not output_text:
            continue
        if output_text not in flattened_parts:
            flattened_parts.append(output_text)

    return ', '.join(flattened_parts).strip(' ,')


def mediate_gpt_image_prompt(prompt, optimization_level=OPTIMIZATION_LEVEL_BALANCED):
    original_prompt = str(prompt or '').strip()
    normalized_level = _normalize_optimization_level(optimization_level)
    if not original_prompt:
        return {
            'original_prompt': '',
            'optimized_prompt': '',
            'short_visual_prompt': '',
            'optimization_level': normalized_level,
            'changed': False,
            'applied_rules': [],
            'rewrite_details': [],
            'structured_outline': [],
        }

    normalized_prompt = original_prompt.replace('\r\n', '\n').replace('\r', '\n')

    raw_segments = []
    for line in normalized_prompt.split('\n'):
        stripped_line = str(line or '').strip()
        if not stripped_line:
            continue
        if _should_keep_line_intact(stripped_line):
            pieces = [stripped_line]
        else:
            pieces = [piece for piece in re.split(r'[,，]', stripped_line) if piece and piece.strip()]
        if pieces:
            raw_segments.extend(pieces)

    if not raw_segments:
        raw_segments = [normalized_prompt]

    normalized_segments = []
    applied_rules = []
    seen = set()
    rewrite_details = []

    for segment in raw_segments:
        segment_info = _normalize_segment(segment, normalized_level)
        if not segment_info or not segment_info['optimized_text']:
            continue

        dedupe_key = (segment_info.get('output_text') or segment_info['optimized_text']).casefold()
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        normalized_segments.append(segment_info)
        applied_rules.extend(segment_info['applied_rules'])
        for rewrite_detail in segment_info['rewrite_details']:
            detail_key = (rewrite_detail['before'], rewrite_detail['after'], rewrite_detail['reason'])
            if detail_key not in {(item['before'], item['after'], item['reason']) for item in rewrite_details}:
                rewrite_details.append(rewrite_detail)

    structured_outline = _build_structured_outline(normalized_segments)
    flattened_prompt = _build_flattened_prompt(normalized_segments)
    short_visual_prompt = flattened_prompt or _build_short_visual_prompt(structured_outline)
    optimized_prompt = original_prompt if normalized_level == OPTIMIZATION_LEVEL_OFF else flattened_prompt

    if not optimized_prompt:
        optimized_prompt = original_prompt

    return {
        'original_prompt': original_prompt,
        'optimized_prompt': optimized_prompt,
        'short_visual_prompt': short_visual_prompt,
        'optimization_level': normalized_level,
        'changed': optimized_prompt != original_prompt,
        'applied_rules': list(dict.fromkeys(applied_rules)),
        'rewrite_details': rewrite_details,
        'structured_outline': structured_outline,
    }