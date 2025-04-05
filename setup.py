from setuptools import find_packages, setup
from NFTorrent import __meta__
 
def read(f):
    return open(f, 'r', encoding='utf-8').read()
 
setup(
    name='ton-nft-torrent',
    version=__meta__.__version__,
    url='https://github.com/xeronm/nft-torrent',
    license='GNU General Public License v3 (GPLv3)',
    description=__meta__.__description__,
    long_description=read('README.md'),
    long_description_content_type='text/markdown',
    maintainer='Denis Muratov',
    maintainer_email='denis.muratov@nexign.com',
    packages=find_packages(exclude=['test*']),
    include_package_data=True,
    install_requires=open('requirements.txt').readlines(),
    python_requires=">=3.9",
    zip_safe=True,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Framework :: FastAPI',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Internet :: WWW/HTTP',
    ],
    project_urls={
    },
)