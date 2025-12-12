"""Framework detection for MU-SIGMA training pairs.

Detects frameworks used in a codebase by analyzing import edges in the mubase.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Framework signatures: import patterns that indicate framework usage
# Format: framework_name -> list of import patterns (any match = detected)
#
# IMPORTANT: Patterns must be specific to avoid false positives:
# - Use path separators (/, ::, .) to require package boundaries
# - Use full import statements where needed
# - Avoid generic words that match variable/function names
FRAMEWORK_SIGNATURES: dict[str, list[str]] = {
    # Python frameworks - use package names with boundaries
    "fastapi": ["fastapi.", "fastapi/", "from fastapi", "import fastapi"],
    "flask": ["flask.", "flask/", "from flask", "import flask"],
    "django": ["django.", "django/", "from django", "import django"],
    "pytorch": ["torch.", "torch/", "from torch", "import torch", "pytorch"],
    "tensorflow": [
        "tensorflow.",
        "tensorflow/",
        "from tensorflow",
        "import tensorflow",
    ],
    "pandas": ["pandas.", "pandas/", "from pandas", "import pandas"],
    "sqlalchemy": ["sqlalchemy.", "sqlalchemy/", "from sqlalchemy", "import sqlalchemy"],
    "numpy": ["numpy.", "numpy/", "from numpy", "import numpy"],
    "scikit-learn": ["sklearn.", "sklearn/", "from sklearn", "import sklearn"],
    "celery": ["celery.", "celery/", "from celery", "import celery"],
    "pydantic": ["pydantic.", "pydantic/", "from pydantic", "import pydantic"],
    "pytest": ["pytest.", "pytest/", "from pytest", "import pytest"],
    "aiohttp": ["aiohttp.", "aiohttp/", "from aiohttp", "import aiohttp"],
    "httpx": ["httpx.", "httpx/", "from httpx", "import httpx"],
    "requests": ["requests.", "requests/", "from requests", "import requests"],
    # TypeScript/JavaScript frameworks - use package paths or scoped packages
    "react": ["react/", "from 'react'", 'from "react"', "react-dom"],
    "vue": ["vue/", "from 'vue'", 'from "vue"', "@vue/"],
    "angular": ["@angular/"],
    "nextjs": ["next/", "@next/", "from 'next'", 'from "next"'],
    "express": [
        "express/",
        "from 'express'",
        'from "express"',
        "require('express')",
        'require("express")',
    ],
    "nestjs": ["@nestjs/"],
    "shadcn": ["@radix-ui/", "@shadcn/"],
    "tailwind": ["tailwindcss/", "tailwindcss."],
    "vite": ["vite/", "from 'vite'", 'from "vite"', "@vitejs/"],
    "webpack": ["webpack/", "from 'webpack'", 'from "webpack"'],
    "jest": ["jest/", "@jest/", "from 'jest'", 'from "jest"'],
    "vitest": ["vitest/", "from 'vitest'", 'from "vitest"'],
    "prisma": ["@prisma/"],
    "drizzle": ["drizzle-orm/", "drizzle-orm."],
    # Rust frameworks - use crate paths with ::
    "tokio": ["tokio::", "tokio/"],
    "axum": ["axum::", "axum/"],
    "actix": ["actix::", "actix-web::", "actix_web::"],
    "serde": ["serde::", "serde/", "serde_"],
    "diesel": ["diesel::", "diesel/"],
    "sqlx": ["sqlx::", "sqlx/"],
    "rocket": ["rocket::", "rocket/"],
    "warp": ["warp::", "warp/"],
    "hyper": ["hyper::", "hyper/"],
    "tracing": ["tracing::", "tracing/", "tracing_"],
    # Go frameworks - full module paths
    "gin": ["github.com/gin-gonic/gin"],
    "fiber": ["github.com/gofiber/fiber"],
    "echo": ["github.com/labstack/echo"],
    "gorm": ["gorm.io/gorm"],
    "chi": ["github.com/go-chi/chi"],
    "gorilla": ["github.com/gorilla/mux"],
    "cobra": ["github.com/spf13/cobra"],
    "viper": ["github.com/spf13/viper"],
    "zap": ["go.uber.org/zap"],
    "logrus": ["github.com/sirupsen/logrus"],
    "testify": ["github.com/stretchr/testify"],
    # Java frameworks - use package prefixes
    "spring": ["org.springframework.", "springframework."],
    "hibernate": ["org.hibernate.", "hibernate."],
    "junit": ["org.junit.", "junit."],
    "lombok": ["lombok."],
    "jackson": ["com.fasterxml.jackson."],
    "mockito": ["org.mockito.", "mockito."],
    # C# frameworks - use namespace prefixes
    "aspnet": ["Microsoft.AspNetCore.", "AspNetCore."],
    "entityframework": ["Microsoft.EntityFrameworkCore.", "EntityFramework."],
    "xunit": ["Xunit.", "xunit."],
    "nunit": ["NUnit.", "nunit."],
    "newtonsoft": ["Newtonsoft.Json."],
    "automapper": ["AutoMapper."],
    "mediatr": ["MediatR."],
}


def detect_frameworks(mubase_path: Path) -> list[str]:
    """Detect frameworks used in a codebase by analyzing import edges.

    Args:
        mubase_path: Path to the .mubase file

    Returns:
        Sorted list of detected framework names
    """
    from mu.kernel import MUbase

    detected: set[str] = set()

    try:
        db = MUbase(mubase_path, read_only=True)

        # Query all import targets from edges table
        result = db.conn.execute(
            """
            SELECT DISTINCT target_id
            FROM edges
            WHERE type = 'imports'
            """
        ).fetchall()

        # Collect all import targets (node IDs contain the import path)
        import_targets: set[str] = set()
        for (target_id,) in result:
            import_targets.add(target_id.lower())

        # Also check node names directly for external dependencies
        external_result = db.conn.execute(
            """
            SELECT DISTINCT name
            FROM nodes
            WHERE type = 'external'
            """
        ).fetchall()

        for (name,) in external_result:
            import_targets.add(name.lower())

        db.close()

        # Match against framework signatures
        for framework, patterns in FRAMEWORK_SIGNATURES.items():
            for pattern in patterns:
                pattern_lower = pattern.lower()
                for target in import_targets:
                    if pattern_lower in target:
                        detected.add(framework)
                        break
                if framework in detected:
                    break

    except Exception as e:
        logger.debug(f"Error detecting frameworks from {mubase_path}: {e}")

    result_list = sorted(detected)
    if result_list:
        logger.debug(f"Detected frameworks: {result_list}")
    return result_list


def get_framework_category(framework: str) -> str:
    """Get the category of a framework.

    Returns one of: web, ml, data, testing, orm, utility
    """
    categories = {
        # Web frameworks
        "fastapi": "web",
        "flask": "web",
        "django": "web",
        "express": "web",
        "nestjs": "web",
        "nextjs": "web",
        "react": "web",
        "vue": "web",
        "angular": "web",
        "axum": "web",
        "actix": "web",
        "rocket": "web",
        "warp": "web",
        "gin": "web",
        "fiber": "web",
        "echo": "web",
        "chi": "web",
        "gorilla": "web",
        "cobra": "utility",
        "viper": "utility",
        "zap": "utility",
        "logrus": "utility",
        "testify": "testing",
        "spring": "web",
        "aspnet": "web",
        "aiohttp": "web",
        "hyper": "web",
        # ML/AI frameworks
        "pytorch": "ml",
        "tensorflow": "ml",
        "scikit-learn": "ml",
        # Data frameworks
        "pandas": "data",
        "numpy": "data",
        # ORM/Database
        "sqlalchemy": "orm",
        "prisma": "orm",
        "drizzle": "orm",
        "diesel": "orm",
        "sqlx": "orm",
        "gorm": "orm",
        "hibernate": "orm",
        "entityframework": "orm",
        # Testing
        "pytest": "testing",
        "jest": "testing",
        "vitest": "testing",
        "junit": "testing",
        "xunit": "testing",
        "nunit": "testing",
        "mockito": "testing",
        # Utility
        "serde": "utility",
        "pydantic": "utility",
        "celery": "utility",
        "httpx": "utility",
        "requests": "utility",
        "tokio": "utility",
        "tracing": "utility",
        "shadcn": "utility",
        "tailwind": "utility",
        "vite": "utility",
        "webpack": "utility",
        "lombok": "utility",
        "jackson": "utility",
        "newtonsoft": "utility",
        "automapper": "utility",
        "mediatr": "utility",
    }
    return categories.get(framework, "utility")
