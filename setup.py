from setuptools import setup, find_packages

setup(
    name="qts-data",
    version="0.1.0",
    description="QTS 量化交易数据包 - A股行情/K线/宏观/行业数据",
    author="QTS",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "pandas>=2.0",
    ],
    package_data={
        "qts_data": [],
    },
    # 数据文件在包外部（qts/00-研究/），通过运行时路径定位
)
