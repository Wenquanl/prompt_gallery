from django.core.management.base import BaseCommand

from .scan_visuals import Command as ScanVisualsCommand

class Command(BaseCommand):
    help = '兼容旧入口：扫描本地视频并建立 visuals 资源库索引'

    def add_arguments(self, parser):
        parser.add_argument('input_folder', type=str)
        parser.add_argument('output_folder', type=str, nargs='?')

    def handle(self, *args, **kwargs):
        nested = ScanVisualsCommand()
        nested.stdout = self.stdout
        nested.stderr = self.stderr
        nested.handle(
            source_path=kwargs['input_folder'],
            name=None,
            resource_types=['video'],
            skip_missing_check=False,
        )