import mimetypes
from pathlib import Path

from django.core.management.base import BaseCommand

from visuals.sync import ensure_source_root, sync_source_root
class Command(BaseCommand):
    help = '扫描本地资源目录，建立 visuals 资源库索引'

    def add_arguments(self, parser):
        parser.add_argument('source_path', type=str)
        parser.add_argument('--name', type=str, help='资源源名称，默认使用目录名')
        parser.add_argument(
            '--resource-types',
            nargs='*',
            default=['image', 'gif', 'video', 'model'],
            choices=['image', 'gif', 'video', 'model', 'other'],
            help='限制扫描的资源类型',
        )
        parser.add_argument('--skip-missing-check', action='store_true', help='跳过缺失文件标记')

    def handle(self, *args, **options):
        source_path = Path(options['source_path']).expanduser().resolve()
        if not source_path.exists() or not source_path.is_dir():
            self.stdout.write(self.style.ERROR('错误：资源根目录不存在'))
            return

        source_name = options['name'] or source_path.name
        source_root = ensure_source_root(source_path, source_name)
        summary = sync_source_root(
            source_root,
            enabled_types=options['resource_types'],
            skip_missing_check=options['skip_missing_check'],
            queue_index=True,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"扫描完成：新增 {summary['created']}，更新 {summary['updated']}，入队 {summary['queued']}，标记缺失 {summary['missing']}。"
            )
        )