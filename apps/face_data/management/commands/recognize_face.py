from django.core.management.base import BaseCommand

from apps.face_data.services import RecognitionSearchService


class Command(BaseCommand):
    help = "Bitta rasm uchun recognition + decision qaytaradi"

    def add_arguments(self, parser):
        parser.add_argument("--image", type=str, required=True, help="Test image path")
        parser.add_argument("--organization-id", type=int, default=None)
        parser.add_argument("--top-k", type=int, default=5)
        parser.add_argument("--accept-threshold", type=float, default=0.70)
        parser.add_argument("--review-threshold", type=float, default=0.55)

    def handle(self, *args, **options):
        image_path = options["image"]
        organization_id = options["organization_id"]
        top_k = options["top_k"]
        accept_threshold = options["accept_threshold"]
        review_threshold = options["review_threshold"]

        service = RecognitionSearchService()
        result = service.decide_match(
            image_path=image_path,
            organization_id=organization_id,
            top_k=top_k,
            accept_threshold=accept_threshold,
            review_threshold=review_threshold,
        )

        self.stdout.write(self.style.SUCCESS("Recognition decision tugadi"))
        self.stdout.write(f"Query image: {result['query_image']}")
        self.stdout.write(f"Organization: {result['organization_id']}")
        self.stdout.write(f"Decision: {result['decision']}")

        best = result["best_match"]
        if best:
            self.stdout.write("------ BEST MATCH ------")
            self.stdout.write(
                f"{best['full_name']} | PINFL={best['pinfl']} | "
                f"score={best['best_score']} | photo_type={best['photo_type']} | "
                f"emb_count={best['score_count']}"
            )

        self.stdout.write("------ TOP CANDIDATES ------")
        for i, row in enumerate(result["top_candidates"], start=1):
            self.stdout.write(
                f"{i}. {row['full_name']} | PINFL={row['pinfl']} | "
                f"best={row['best_score']} | top3avg={row['top3_avg_score']}"
            )