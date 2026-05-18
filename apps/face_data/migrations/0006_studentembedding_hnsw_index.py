from django.db import migrations
from pgvector.django import HnswIndex


class Migration(migrations.Migration):

    dependencies = [
        ('face_data', '0005_remove_facedata_model'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='studentembedding',
            index=HnswIndex(
                fields=['embedding'],
                name='se_emb_hnsw_cosine_idx',
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
        ),
    ]
