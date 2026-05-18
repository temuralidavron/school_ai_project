from django.core.management.base import BaseCommand

from apps.face_data.services import RecognitionSearchService


class Command(BaseCommand):
    help = "Bitta rasmni bazadagi student embeddinglari bilan solishtiradi"

    def add_arguments(self, parser):
        parser.add_argument("--image", type=str, required=True, help="Test image path")
        parser.add_argument("--organization-id", type=int, default=None)
        parser.add_argument("--top-k", type=int, default=5)

    def handle(self, *args, **options):
        image_path = options["image"]
        organization_id = options["organization_id"]
        top_k = options["top_k"]

        service = RecognitionSearchService()
        result = service.search(
            image_path=image_path,
            organization_id=organization_id,
            top_k=top_k,
        )

        self.stdout.write(self.style.SUCCESS("Recognition search tugadi"))
        self.stdout.write(f"Query image: {result['query_image']}")
        self.stdout.write(f"Organization: {result['organization_id']}")
        self.stdout.write("------ TOP RESULTS ------")

        for i, row in enumerate(result["results"], start=1):
            self.stdout.write(
                f"{i}. {row['full_name']} | PINFL={row['pinfl']} | "
                f"best={row['best_score']} | top3avg={row['top3_avg_score']} | "
                f"photo_type={row['photo_type']} | emb_count={row['score_count']}"
            )