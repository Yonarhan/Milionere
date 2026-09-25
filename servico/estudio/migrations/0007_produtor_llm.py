from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estudio", "0006_cancelar"),
    ]

    operations = [
        migrations.AddField(
            model_name="produtor",
            name="llm",
            field=models.CharField(default="claude-cli", max_length=10),
        ),
    ]