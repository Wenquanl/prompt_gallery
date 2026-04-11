from django.core.management.base import BaseCommand

from visuals.models import SourceRoot
from visuals.sync import sync_source_root


class Command(BaseCommand):
    help = '同步所有启用中的本地资源源到 visuals 轻索引层'

    def add_arguments(self, parser):
        parser.add_argument('--skip-missing-check', action='store_true', help='跳过缺失文件标记')
        parser.add_argument('--no-index', action='store_true', help='只刷新索引记录，不触发元数据重建任务')

    def handle(self, *args, **options):
        total_created = 0
        total_updated = 0
        total_queued = 0
        total_missing = 0

        for source_root in SourceRoot.objects.filter(is_enabled=True).order_by('name'):
            try:
                summary = sync_source_root(
                    source_root,
                    skip_missing_check=options['skip_missing_check'],
                    queue_index=not options['no_index'],
                )
            except FileNotFoundError:
                self.stdout.write(self.style.WARNING(f'跳过不存在的资源源: {source_root.root_path}'))
                continue

            total_created += summary['created']
            total_updated += summary['updated']
            total_queued += summary['queued']
            total_missing += summary['missing']
            self.stdout.write(
                f"[{source_root.name}] 新增 {summary['created']}，更新 {summary['updated']}，入队 {summary['queued']}，缺失 {summary['missing']}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'同步完成：新增 {total_created}，更新 {total_updated}，入队 {total_queued}，标记缺失 {total_missing}。'
            )
        )