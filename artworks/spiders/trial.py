# -*- coding: utf-8 -*-
import re
import scrapy

from scrapy.http  import Request
from scrapy.item import Field, Item
from scrapy.loader import ItemLoader
from scrapy.loader.processors import MapCompose, TakeFirst
from urllib.parse import urlparse, urljoin

class UtilsMixin(object):
    def sanitize_category(self, category):
        """
        sanitize_category
            Utility function to sanatize category so that category from differnt source can be
            caompared. To sanitize a category remove all spaces and lowercase it.
            :param category: it can be string or list of category
            :return: sanatized category or list of category
        """
        sanitizer = lambda x:x.lower().replace(' ','')

        if type(category) in (list, tuple):
            category = list(map(sanitizer, category))
        else:
            category = sanitizer(category)
        return category

    def get_base_href(self, url):
        """
        get_base_href
            Utility function to get base url from complete url.
            :param url: any URI
            :return: base url
        """
        parsed_uri = urlparse(url)
        return '{uri.scheme}://{uri.netloc}/'.format(uri=parsed_uri)

    def extract_physical_dimension(self, details, type='width'):
        """
        extract_physical_dimension
            Utility function to extract phisical size of art.
            :param details: physical dimension details
            :param type: possible value `width` or `height`
            :return: `hight` of `width` as per request
            :Note - i) It will use `sheet` specifications to determine physical dimensions.
                    ii) Can be extended frther to return width and hight both if needed.
        """
        mach = re.match('.*\((\d+\.\d+)\s+x\s(\d+\.\d+)\scm\)\s+\(sheet\)', details)
        if mach:
            dimensions = {'height': mach.group(1), 'width':mach.group(2)}
            return float(dimensions[type])
        return None

class TrialSpider(scrapy.Spider, UtilsMixin):
    name = 'trial'
    previous_text = 'Prev'
    next_text = 'Next'

    # ACC- scrape all works in the `In Sunsh` and `Summertime` categories. Hence lets keep
    # them in allowed category.
    allowed_categories = ('In Sunsh', 'Summertime')

    start_urls = (
        'http://pstrial-a-2018-10-19.toscrape.com/browse/',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = self.get_base_href(self.start_urls[0])

    def parse(self, response):
        """
        parse
            This is trigger point for crawler and restrict spider to scrape all works in the
            `In Sunsh` and `Summertime` categories and return request object for selected
             categories URLs.
        """
        allowed_categories = self.sanitize_category(self.allowed_categories)

        for sel in response.xpath('//*[@id="subcats"]/div/a'):
            category = sel.xpath('./h3/text()')[0].extract()
            s_category = self.sanitize_category(category)

            # if category is one of the allowed category then only crawl it further.
            if s_category in allowed_categories:
                relative_url = sel.xpath('@href')[0].extract()
                absolute_url = urljoin(self.base_url, relative_url)
                yield Request(
                    absolute_url, meta={'browse_path':[category]}, callback=self.parse_subcategory
                )

    def parse_subcategory(self, response):
        """
        parse_subcategory
            A category can have multiple sub categories. This function is responsible to extract
            all sub-categories under a category. If category dont have any subcategory then
            parse the art work for it.
            Note - Apart from root level all `Category` or `sub-category` will have 0 or more
            `sub-category`.
        """
        # go down to `category tree` unless reaches to a `sub-category` which dont have any other
        # sub-category.
        sub_category_selectors = response.xpath('//*[@id="subcats"]/div/a')

        # if no sub-category then process the art work in page.
        if not sub_category_selectors:
            yield from self.parse_art_list(response)

        # calculate `absolute_url` and `path` of sub-category resursively.
        for sel in sub_category_selectors:
            browse_path = response.meta['browse_path'].copy()
            sub_category = sel.xpath('h3/text()')[0].extract()
            browse_path.append(sub_category)
            relative_url = sel.xpath('@href')[0].extract()
            absolute_url = urljoin(self.base_url, relative_url)
            yield Request(
                absolute_url, meta={'browse_path':browse_path}, callback=self.parse_subcategory
            )

    def parse_art_list(self, response):
        """
        parse_art_list
            This function will parse the list of art work for a sub-category and return
            generator of each art work.
        """
        art_selector = response.xpath('//*[@id="body"]/div[2]/a')
        for art in art_selector:
            browse_path = response.meta['browse_path'].copy()
            relative_url = art.xpath('@href')[0].extract()
            absolute_url = urljoin(self.base_url, relative_url)
            link_text = art.xpath('text()')[0].extract().lower()

            callback = self.parse_art
            if link_text == self.previous_text.lower():
                continue
            elif link_text == self.next_text.lower():
                callback = self.parse_art_list

            yield Request(
                absolute_url,
                meta={'browse_path':browse_path, 'url':absolute_url},
                callback=callback
            )

    def parse_art(self, response):
        """
        part_art
            This function will extract data relevant for a art work.
            ('url', 'title', 'image', 'height', 'width', 'description') will be single valued.
            ('artist', 'path') can be a list.
        """
        item = Item()
        item_loader = ItemLoader(item=item, response=response)
        items_list = ('url', 'title', 'image', 'height', 'width', 'description' )
        for name in items_list:
            item.fields[name] = Field(output_processor=TakeFirst())
        item.fields['artist'] = Field()
        item.fields['path'] = Field()

        item_loader.add_value('url', response.meta['url'])
        item_loader.add_xpath('artist', '//*[@id="content"]/h2/text()')
        item_loader.add_xpath('title', '//*[@id="content"]/h1/text()')
        item_loader.add_xpath(
            'image',
            '//*[@id="body"]/img/@src',
            MapCompose(lambda x: urljoin(self.base_url,x))
        )
        item_loader.add_xpath(
            'height',
            '//*[@id="content"]/dl/dd[3]/text()',
            MapCompose(lambda x: self.extract_physical_dimension(x, type='height'))
        )
        item_loader.add_xpath(
            'width',
            '//*[@id="content"]/dl/dd[3]/text()',
            MapCompose(lambda x: self.extract_physical_dimension(x, type='width'))
        )
        item_loader.add_xpath('description', '//*[@id="content"]/div/p/text()')
        item_loader.add_value('path', response.meta['browse_path'])
        return item_loader.load_item()
