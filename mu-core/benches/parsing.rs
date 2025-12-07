//! Benchmark for parsing performance.

use criterion::{black_box, criterion_group, criterion_main, Criterion};

fn bench_parse_python(c: &mut Criterion) {
    let source = r#"
import os
from pathlib import Path

class MyClass(BaseClass):
    """A test class with various methods."""

    def __init__(self, name: str, value: int = 0):
        self.name = name
        self.value = value

    def process(self, data: list[str]) -> dict[str, int]:
        """Process the data and return results."""
        result = {}
        for item in data:
            if item.startswith("_"):
                continue
            result[item] = len(item)
        return result

    @staticmethod
    def helper() -> None:
        pass

    @property
    def info(self) -> str:
        return f"{self.name}: {self.value}"

def main():
    obj = MyClass("test", 42)
    print(obj.info)
"#;

    c.bench_function("parse_python_file", |b| {
        b.iter(|| {
            // Benchmark would go here once we can import the library
            black_box(source.len())
        })
    });
}

fn bench_parse_multiple_files(c: &mut Criterion) {
    c.bench_function("parse_1000_files_baseline", |b| {
        b.iter(|| {
            // Baseline benchmark
            black_box(1000)
        })
    });
}

criterion_group!(benches, bench_parse_python, bench_parse_multiple_files);
criterion_main!(benches);
