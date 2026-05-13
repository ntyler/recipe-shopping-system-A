from PushShoppingList.services.food_rules_service import annotate_product_food_rules
from PushShoppingList.services.food_rules_service import load_food_rules


def mark_product_food_rules(product):
    return annotate_product_food_rules(product)


def mark_products_food_rules(products):
    return [
        mark_product_food_rules(product)
        for product in products
    ]


if __name__ == "__main__":
    rules = load_food_rules()
    print(f"Loaded {len(rules['require'])} required food rule(s).")
    print(f"Loaded {len(rules['avoid'])} avoid food rule(s).")
