from django.db import migrations
from pgvector.django import VectorField


class Migration(migrations.Migration):

    dependencies = [
        ("face_data", "0002_enrollmentphoto_studentembedding"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS vector",
            reverse_sql="",
        ),

        # Add new vector column alongside old JSON column
        migrations.RunSQL(
            "ALTER TABLE student_embeddings ADD COLUMN embedding_v vector(512)",
            reverse_sql="ALTER TABLE student_embeddings DROP COLUMN IF EXISTS embedding_v",
        ),

        # Copy data: JSON array text → vector
        migrations.RunSQL(
            "UPDATE student_embeddings SET embedding_v = embedding::text::vector",
            reverse_sql="",
        ),

        # Swap columns
        migrations.RunSQL(
            sql="""
                ALTER TABLE student_embeddings DROP COLUMN embedding;
                ALTER TABLE student_embeddings RENAME COLUMN embedding_v TO embedding;
            """,
            reverse_sql="",
        ),

        # HNSW index for fast cosine similarity search
        migrations.RunSQL(
            "CREATE INDEX student_embeddings_embedding_hnsw ON student_embeddings USING hnsw (embedding vector_cosine_ops)",
            reverse_sql="DROP INDEX IF EXISTS student_embeddings_embedding_hnsw",
        ),

        # Sync Django model state (DB already changed above)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="studentembedding",
                    name="embedding",
                    field=VectorField(dimensions=512),
                ),
            ]
        ),
    ]
