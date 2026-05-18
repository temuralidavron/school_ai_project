from django.core.management.base import BaseCommand

from apps.face_data.services import EmbeddingGenerationService


class Command(BaseCommand):
    help = "Valid enrollment rasmlaridan embedding yaratadi"

    def add_arguments(self, parser):
        parser.add_argument("--organization-id", type=int, default=None)
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        organization_id = options["organization_id"]
        limit = options["limit"]

        service = EmbeddingGenerationService()

        batch_result = service.process_batch(
            organization_id=organization_id,
            limit=limit,
        )
        primary_result = service.mark_primary_embeddings(
            organization_id=organization_id
        )

        self.stdout.write(self.style.SUCCESS("Embedding generation tugadi"))
        self.stdout.write("------ BATCH RESULT ------")
        for key, value in batch_result.items():
            self.stdout.write(f"{key}: {value}")

        self.stdout.write("------ PRIMARY RESULT ------")
        for key, value in primary_result.items():
            self.stdout.write(f"{key}: {value}")