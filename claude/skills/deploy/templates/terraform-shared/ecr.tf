###############################################################################
# ecr.tf — Container registry for the app image.
#
# GitHub Actions pushes `:latest` (and a git SHA tag) here. App Runner auto-
# deploys when `:latest` changes.
#
# CSIP is a single full-stack app, so the repo is just the project name (no
# `-backend` suffix — there is no separate backend to disambiguate).
###############################################################################

resource "aws_ecr_repository" "app" {
  name                 = var.project_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = var.project_name
  }
}

# Keep the last 10 untagged image versions, expire the rest.
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep only the 10 most recent untagged images"
        selection = {
          tagStatus   = "untagged"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
