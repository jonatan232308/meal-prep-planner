"""
Meal Prep Planner — Full-Stack Web App
Flask backend with SQLite database for syncing across devices.
"""

import os
import secrets
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///meals.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
CORS(app)

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE MODELS
# ══════════════════════════════════════════════════════════════════════════════

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    selections = db.relationship("Selection", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Meal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(20), nullable=False)  # breakfast, lunch, dinner
    calories = db.Column(db.Integer, default=0)
    prep_time = db.Column(db.String(50))
    description = db.Column(db.Text)
    ingredients = db.Column(db.Text)  # JSON array stored as text
    steps = db.Column(db.Text)  # JSON array stored as text
    is_default = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "calories": self.calories,
            "prepTime": self.prep_time,
            "description": self.description,
            "ingredients": json.loads(self.ingredients) if self.ingredients else [],
            "steps": json.loads(self.steps) if self.steps else [],
            "isDefault": self.is_default,
            "createdBy": self.created_by,
        }


class Selection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    meal_id = db.Column(db.Integer, db.ForeignKey("meal.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "meal_id"),)


# ══════════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_current_user():
    user_id = session.get("user_id")
    if user_id:
        return db.session.get(User, user_id)
    return None


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_user():
            return jsonify({"error": "Not logged in"}), 401
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════════════════════
# PAGE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    user = get_current_user()
    if not user:
        return redirect(url_for("login_page"))
    return render_template("index.html", username=user.username)


@app.route("/login")
def login_page():
    if get_current_user():
        return redirect(url_for("index"))
    return render_template("login.html")


# ══════════════════════════════════════════════════════════════════════════════
# AUTH API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json()
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already taken"}), 400

    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    session["user_id"] = user.id
    return jsonify({"message": "Account created!", "username": user.username})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid username or password"}), 401

    session["user_id"] = user.id
    return jsonify({"message": "Logged in!", "username": user.username})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return jsonify({"message": "Logged out"})


@app.route("/api/me")
def me():
    user = get_current_user()
    if user:
        return jsonify({"username": user.username, "id": user.id})
    return jsonify({"error": "Not logged in"}), 401


# ══════════════════════════════════════════════════════════════════════════════
# MEALS API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/meals")
@login_required
def get_meals():
    user = get_current_user()
    # Return all default meals + custom meals created by anyone
    meals = Meal.query.filter(
        db.or_(Meal.is_default == True, Meal.created_by == user.id)
    ).all()
    return jsonify([m.to_dict() for m in meals])


@app.route("/api/meals", methods=["POST"])
@login_required
def create_meal():
    import json
    user = get_current_user()
    data = request.get_json()

    meal = Meal(
        name=data["name"],
        category=data["category"],
        calories=data.get("calories", 0),
        prep_time=data.get("prepTime", ""),
        description=data.get("description", ""),
        ingredients=json.dumps(data.get("ingredients", [])),
        steps=json.dumps(data.get("steps", [])),
        is_default=False,
        created_by=user.id,
    )
    db.session.add(meal)
    db.session.commit()
    return jsonify(meal.to_dict()), 201


@app.route("/api/meals/<int:meal_id>", methods=["DELETE"])
@login_required
def delete_meal(meal_id):
    user = get_current_user()
    meal = db.session.get(Meal, meal_id)
    if not meal:
        return jsonify({"error": "Meal not found"}), 404
    if meal.is_default:
        return jsonify({"error": "Cannot delete default meals"}), 403
    if meal.created_by != user.id:
        return jsonify({"error": "Not your meal"}), 403

    Selection.query.filter_by(meal_id=meal_id).delete()
    db.session.delete(meal)
    db.session.commit()
    return jsonify({"message": "Deleted"})


# ══════════════════════════════════════════════════════════════════════════════
# SELECTIONS API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/selections")
@login_required
def get_selections():
    user = get_current_user()
    selections = Selection.query.filter_by(user_id=user.id).all()
    return jsonify([s.meal_id for s in selections])


@app.route("/api/selections/<int:meal_id>", methods=["POST"])
@login_required
def add_selection(meal_id):
    user = get_current_user()
    existing = Selection.query.filter_by(user_id=user.id, meal_id=meal_id).first()
    if existing:
        return jsonify({"message": "Already selected"})
    selection = Selection(user_id=user.id, meal_id=meal_id)
    db.session.add(selection)
    db.session.commit()
    return jsonify({"message": "Selected"})


@app.route("/api/selections/<int:meal_id>", methods=["DELETE"])
@login_required
def remove_selection(meal_id):
    user = get_current_user()
    Selection.query.filter_by(user_id=user.id, meal_id=meal_id).delete()
    db.session.commit()
    return jsonify({"message": "Removed"})


@app.route("/api/selections", methods=["DELETE"])
@login_required
def clear_selections():
    user = get_current_user()
    Selection.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    return jsonify({"message": "Cleared"})


# ══════════════════════════════════════════════════════════════════════════════
# SEED DEFAULT MEALS
# ══════════════════════════════════════════════════════════════════════════════

def seed_defaults():
    """Insert 50 default meals if they don't exist yet."""
    import json
    if Meal.query.filter_by(is_default=True).count() >= 50:
        return

    defaults = [
        # BREAKFAST
        {"name":"Overnight Oats","category":"breakfast","calories":320,"prep_time":"5 min","description":"Creamy no-cook oats packed with fiber and protein.","ingredients":["1/2 cup rolled oats","1/2 cup almond milk","1/4 cup Greek yogurt","1 tbsp chia seeds","1/2 cup mixed berries","1 tsp honey"],"steps":["Combine oats, milk, yogurt, and chia seeds in a jar","Stir well and seal the lid","Refrigerate overnight (at least 6 hours)","Top with berries and honey before eating","Can store up to 4 days in fridge"]},
        {"name":"Egg Muffin Cups","category":"breakfast","calories":280,"prep_time":"25 min","description":"Grab-and-go protein-packed egg cups with veggies.","ingredients":["8 large eggs","1/2 cup diced bell peppers","1/4 cup diced onion","1/2 cup spinach","Salt and pepper","Cooking spray"],"steps":["Preheat oven to 375F (190C)","Spray a 12-cup muffin tin with cooking spray","Whisk eggs with salt and pepper","Divide veggies evenly into muffin cups","Pour egg mixture over veggies","Bake for 20 minutes until set","Cool and store in fridge up to 5 days"]},
        {"name":"Banana Protein Pancakes","category":"breakfast","calories":310,"prep_time":"15 min","description":"3-ingredient pancakes — high protein, no flour needed.","ingredients":["2 ripe bananas","4 eggs","1/2 cup oats","Cinnamon to taste","Cooking spray"],"steps":["Blend bananas, eggs, oats, and cinnamon until smooth","Heat a non-stick pan on medium with cooking spray","Pour 1/4 cup batter per pancake","Cook 2 min per side until golden","Makes about 8 pancakes — store in fridge or freeze"]},
        {"name":"Greek Yogurt Parfait","category":"breakfast","calories":290,"prep_time":"5 min","description":"Layered yogurt with granola and fresh fruit.","ingredients":["1 cup non-fat Greek yogurt","1/4 cup low-sugar granola","1/2 cup mixed berries","1 tbsp honey","1 tbsp sliced almonds"],"steps":["Layer half the yogurt in a jar or container","Add half the granola and berries","Repeat layers","Top with almonds and drizzle honey","Keep granola separate if prepping ahead to stay crunchy"]},
        {"name":"Spinach & Feta Egg Wrap","category":"breakfast","calories":340,"prep_time":"10 min","description":"Quick high-protein wrap with greens.","ingredients":["2 eggs","1 whole wheat tortilla","1 cup fresh spinach","2 tbsp crumbled feta","Salt and pepper"],"steps":["Scramble eggs in a non-stick pan","Add spinach and cook until wilted","Warm the tortilla","Fill with egg mixture and top with feta","Roll up and wrap in foil for meal prep"]},
        {"name":"Chia Seed Pudding","category":"breakfast","calories":260,"prep_time":"5 min","description":"Creamy pudding loaded with omega-3s and fiber.","ingredients":["3 tbsp chia seeds","1 cup almond milk","1 tsp vanilla extract","1 tsp maple syrup","Fresh fruit for topping"],"steps":["Mix chia seeds, milk, vanilla, and maple syrup","Stir well to prevent clumps","Refrigerate for at least 4 hours or overnight","Stir again before serving","Top with fresh fruit"]},
        {"name":"Avocado Toast with Egg","category":"breakfast","calories":350,"prep_time":"10 min","description":"Classic healthy toast — good fats and protein.","ingredients":["1 slice whole grain bread","1/2 avocado","1 egg","Red pepper flakes","Salt and lemon juice"],"steps":["Toast the bread until crispy","Mash avocado with salt and lemon juice","Spread avocado on toast","Fry or poach the egg","Place egg on top and sprinkle red pepper flakes"]},
        {"name":"Smoothie Freezer Packs","category":"breakfast","calories":280,"prep_time":"15 min","description":"Pre-portioned smoothie bags — just blend and go.","ingredients":["1 banana per bag","1/2 cup spinach per bag","1/2 cup frozen berries per bag","1 tbsp flax seeds per bag","Add 1 cup almond milk when blending"],"steps":["Slice bananas","Portion spinach, berries, banana, and flax into freezer bags","Flatten bags and freeze","When ready, dump a bag into blender","Add 1 cup almond milk and blend until smooth","Makes 5-7 bags in one prep session"]},
        {"name":"Turkey Sausage Breakfast Bowl","category":"breakfast","calories":330,"prep_time":"20 min","description":"Savory bowl with lean protein and sweet potato.","ingredients":["4 oz turkey sausage","1 small sweet potato, diced","1 cup spinach","1 egg","1 tsp olive oil"],"steps":["Dice sweet potato into small cubes","Cook sweet potato in olive oil for 10 min until tender","Add crumbled turkey sausage, cook 5 min","Add spinach and cook until wilted","Top with a fried egg","Divide into meal prep containers"]},
        {"name":"Cottage Cheese & Fruit Bowl","category":"breakfast","calories":250,"prep_time":"5 min","description":"High-protein, low-effort breakfast bowl.","ingredients":["1 cup low-fat cottage cheese","1/2 cup pineapple chunks","1 tbsp sunflower seeds","Dash of cinnamon"],"steps":["Scoop cottage cheese into a bowl","Top with pineapple chunks","Sprinkle sunflower seeds and cinnamon","Can be prepped in containers for 3 days"]},
        {"name":"Veggie Frittata Slices","category":"breakfast","calories":300,"prep_time":"30 min","description":"Bake once, eat all week — loaded with vegetables.","ingredients":["8 eggs","1 cup diced zucchini","1/2 cup diced tomatoes","1/4 cup diced onion","1/4 cup shredded cheese","Salt and pepper"],"steps":["Preheat oven to 375F","Whisk eggs with salt and pepper","Saute zucchini, tomatoes, and onion for 5 min","Pour into a greased 9-inch baking dish","Add sauteed veggies and cheese","Bake 25 min until set and golden","Cool, slice into 6 portions, refrigerate"]},
        {"name":"Peanut Butter Banana Oatmeal","category":"breakfast","calories":370,"prep_time":"10 min","description":"Warm and filling oatmeal with natural protein.","ingredients":["1/2 cup rolled oats","1 cup water","1 tbsp peanut butter","1/2 banana sliced","Pinch of salt"],"steps":["Bring water to a boil","Add oats and reduce heat, cook 5 min","Stir in peanut butter until melted","Top with banana slices","Can batch cook 5 servings and reheat"]},
        {"name":"Breakfast Burrito Bowls","category":"breakfast","calories":360,"prep_time":"20 min","description":"All the burrito flavors without the heavy tortilla.","ingredients":["3 eggs scrambled","1/4 cup black beans","2 tbsp salsa","1/4 avocado","2 tbsp shredded cheese"],"steps":["Scramble eggs and season with cumin","Warm black beans","Layer beans, then eggs in a container","Top with salsa, cheese, and avocado","Store up to 4 days (add avocado fresh)"]},
        {"name":"Apple Cinnamon Quinoa Bowl","category":"breakfast","calories":300,"prep_time":"15 min","description":"A warm, nutty alternative to oatmeal.","ingredients":["1/2 cup quinoa","1 cup almond milk","1 small apple diced","1 tsp cinnamon","1 tbsp walnuts","1 tsp honey"],"steps":["Rinse quinoa well","Simmer quinoa in almond milk for 15 min","Stir in cinnamon","Top with diced apple, walnuts, and honey","Stores well for 4 days in fridge"]},
        {"name":"Hard Boiled Eggs & Fruit","category":"breakfast","calories":240,"prep_time":"15 min","description":"The simplest grab-and-go protein breakfast.","ingredients":["2 large eggs","1 medium apple or banana","Pinch of salt"],"steps":["Place eggs in a pot, cover with cold water","Bring to a boil, then cover and remove from heat","Let sit 10 minutes","Transfer to ice water bath","Peel and store with fruit for the week"]},
        {"name":"Protein Waffles","category":"breakfast","calories":330,"prep_time":"15 min","description":"Freezer-friendly waffles with extra protein.","ingredients":["1 cup whole wheat flour","1 scoop protein powder","2 eggs","1 cup milk","1 tbsp honey","1 tsp baking powder"],"steps":["Mix dry ingredients in a bowl","Whisk eggs, milk, and honey separately","Combine wet and dry ingredients","Cook in waffle iron until golden","Cool and freeze — toast to reheat"]},
        {"name":"Mediterranean Egg Cups","category":"breakfast","calories":270,"prep_time":"25 min","description":"Sun-dried tomato and olive egg muffins.","ingredients":["6 eggs","1/4 cup sun-dried tomatoes chopped","2 tbsp kalamata olives chopped","2 tbsp feta cheese","1 tsp dried oregano"],"steps":["Preheat oven to 375F","Whisk eggs with oregano, salt, and pepper","Divide tomatoes and olives into muffin cups","Pour egg mixture over toppings","Sprinkle feta on top","Bake 18-20 minutes","Store in fridge up to 5 days"]},
        # LUNCH
        {"name":"Chicken & Veggie Stir Fry","category":"lunch","calories":380,"prep_time":"20 min","description":"Lean chicken with colorful veggies in light sauce.","ingredients":["6 oz chicken breast","1 cup broccoli florets","1/2 cup bell peppers","1/2 cup snap peas","2 tbsp low-sodium soy sauce","1 tsp sesame oil","1/2 cup brown rice"],"steps":["Cook brown rice according to package","Slice chicken into strips and season","Stir fry chicken in sesame oil until cooked (6 min)","Add vegetables and cook 4 min until crisp-tender","Add soy sauce and toss","Divide rice and stir fry into containers"]},
        {"name":"Turkey & Quinoa Stuffed Peppers","category":"lunch","calories":350,"prep_time":"35 min","description":"Colorful stuffed peppers — lean and filling.","ingredients":["4 bell peppers halved","1 lb ground turkey","1 cup cooked quinoa","1/2 cup diced tomatoes","1 tsp cumin","1/4 cup shredded cheese"],"steps":["Preheat oven to 400F","Halve peppers and remove seeds","Brown ground turkey with cumin","Mix turkey with quinoa and tomatoes","Stuff pepper halves with mixture","Top with cheese and bake 25 min","Cool and store — makes 8 halves"]},
        {"name":"Mason Jar Greek Salad","category":"lunch","calories":340,"prep_time":"15 min","description":"Layered salad that stays fresh all week.","ingredients":["2 tbsp olive oil + lemon dressing","1/2 cup cucumber diced","1/2 cup cherry tomatoes","1/4 cup red onion","1/4 cup kalamata olives","2 tbsp feta","2 cups romaine lettuce"],"steps":["Pour dressing into bottom of mason jar","Layer cucumber, tomatoes, onion, olives","Add feta cheese","Pack lettuce on top (keeps it dry)","Seal and refrigerate up to 5 days","Shake into a bowl when ready to eat"]},
        {"name":"Tuna Lettuce Wraps","category":"lunch","calories":290,"prep_time":"10 min","description":"Low-carb, high-protein wraps in minutes.","ingredients":["1 can tuna drained","2 tbsp Greek yogurt","1 tbsp mustard","1/4 cup diced celery","Butter lettuce leaves","Salt and pepper"],"steps":["Mix tuna, yogurt, mustard, and celery","Season with salt and pepper","Spoon mixture into lettuce leaves","Roll and secure with a toothpick","Store tuna mix separately for meal prep"]},
        {"name":"Chicken Burrito Bowl","category":"lunch","calories":420,"prep_time":"25 min","description":"Chipotle-style bowl made healthy at home.","ingredients":["6 oz chicken breast","1/2 cup brown rice","1/4 cup black beans","1/4 cup corn","2 tbsp salsa","1/4 avocado","Lime juice"],"steps":["Cook rice and season with lime juice","Grill or bake chicken with cumin and chili powder","Warm black beans and corn","Slice chicken","Layer rice, beans, corn, chicken in container","Top with salsa and avocado when serving"]},
        {"name":"Lentil Soup","category":"lunch","calories":310,"prep_time":"30 min","description":"Hearty, fiber-rich soup that freezes beautifully.","ingredients":["1 cup dried lentils","1 can diced tomatoes","2 carrots diced","2 celery stalks diced","1 onion diced","3 cups broth","1 tsp cumin"],"steps":["Saute onion, carrots, and celery for 5 min","Add lentils, tomatoes, broth, and cumin","Bring to a boil then reduce to simmer","Cook 25 min until lentils are tender","Season with salt and pepper","Divide into 4-5 containers","Freezes well for up to 3 months"]},
        {"name":"Shrimp & Zucchini Noodles","category":"lunch","calories":280,"prep_time":"15 min","description":"Low-carb noodle swap with garlic shrimp.","ingredients":["8 oz shrimp peeled","2 medium zucchini spiralized","2 cloves garlic","1 tbsp olive oil","1/4 cup cherry tomatoes","Red pepper flakes"],"steps":["Spiralize zucchini into noodles","Heat olive oil and saute garlic 30 seconds","Add shrimp and cook 3 min per side","Add zucchini noodles and tomatoes","Toss for 2 minutes until just tender","Season and divide into containers"]},
        {"name":"Turkey Meatball Bowl","category":"lunch","calories":370,"prep_time":"30 min","description":"Lean meatballs over greens with light dressing.","ingredients":["1 lb ground turkey","1/4 cup breadcrumbs","1 egg","1 tsp Italian seasoning","4 cups mixed greens","2 tbsp balsamic vinaigrette"],"steps":["Preheat oven to 400F","Mix turkey, breadcrumbs, egg, and seasoning","Roll into 20 small meatballs","Bake on a lined sheet for 18-20 min","Cool meatballs","Divide greens and meatballs into containers","Add dressing when serving"]},
        {"name":"Chickpea & Avocado Smash","category":"lunch","calories":330,"prep_time":"10 min","description":"Mashed chickpea sandwich filling — vegan protein.","ingredients":["1 can chickpeas drained","1/2 avocado","1 tbsp lemon juice","Salt, pepper, garlic powder","Whole grain bread or lettuce wraps"],"steps":["Mash chickpeas and avocado together with a fork","Add lemon juice and seasonings","Mix until chunky-smooth","Serve on bread or in lettuce cups","Stores in fridge 3-4 days"]},
        {"name":"Asian Chicken Lettuce Cups","category":"lunch","calories":300,"prep_time":"15 min","description":"Light and crunchy with savory-sweet sauce.","ingredients":["8 oz ground chicken","1 tbsp soy sauce","1 tsp sriracha","1/2 cup water chestnuts diced","2 green onions","Butter lettuce cups"],"steps":["Brown ground chicken in a pan","Add soy sauce, sriracha, and water chestnuts","Cook 3 more minutes","Stir in sliced green onions","Spoon into lettuce cups","Store filling separately for meal prep"]},
        {"name":"Salmon & Sweet Potato Plate","category":"lunch","calories":410,"prep_time":"25 min","description":"Omega-3 rich salmon with complex carbs.","ingredients":["5 oz salmon fillet","1 medium sweet potato","1 cup steamed broccoli","1 tsp olive oil","Lemon wedge"],"steps":["Preheat oven to 400F","Cube sweet potato and toss with olive oil","Roast sweet potato for 15 min","Add salmon to the sheet pan","Roast together another 12 min","Steam broccoli","Plate with lemon wedge"]},
        {"name":"Black Bean & Corn Salad","category":"lunch","calories":320,"prep_time":"10 min","description":"Fresh Southwestern salad — no cooking needed.","ingredients":["1 can black beans drained","1 cup corn kernels","1/2 cup diced tomato","1/4 cup red onion","2 tbsp cilantro","2 tbsp lime juice","1 tbsp olive oil"],"steps":["Combine all ingredients in a large bowl","Toss with lime juice and olive oil","Season with salt, pepper, and cumin","Refrigerate at least 30 min for flavors to meld","Divide into containers — lasts 5 days"]},
        {"name":"Egg Fried Rice (Cauliflower)","category":"lunch","calories":260,"prep_time":"15 min","description":"Low-carb fried rice using riced cauliflower.","ingredients":["3 cups riced cauliflower","2 eggs","1/2 cup peas and carrots","2 tbsp soy sauce","1 tsp sesame oil","2 green onions"],"steps":["Heat sesame oil in a large pan","Scramble eggs and set aside","Add riced cauliflower and cook 5 min","Add peas, carrots, and soy sauce","Stir in scrambled eggs","Top with green onions","Portion into 3 containers"]},
        {"name":"Mediterranean Wrap","category":"lunch","calories":370,"prep_time":"10 min","description":"Hummus, veggies, and feta in a whole wheat wrap.","ingredients":["1 whole wheat tortilla","3 tbsp hummus","1/4 cup cucumber sliced","1/4 cup roasted red peppers","2 tbsp feta","Handful of spinach"],"steps":["Spread hummus over the tortilla","Layer spinach, cucumber, peppers, and feta","Roll tightly and cut in half","Wrap in foil for meal prep","Stays fresh 2-3 days"]},
        {"name":"Teriyaki Tofu Bowl","category":"lunch","calories":340,"prep_time":"20 min","description":"Crispy baked tofu with teriyaki sauce.","ingredients":["1 block firm tofu pressed","2 tbsp teriyaki sauce","1/2 cup brown rice","1 cup steamed edamame","1/2 cup shredded carrots"],"steps":["Press tofu for 15 min and cube","Bake tofu at 400F for 25 min, flipping halfway","Toss baked tofu with teriyaki sauce","Cook brown rice","Assemble bowls: rice, tofu, edamame, carrots","Drizzle extra teriyaki if desired"]},
        {"name":"Chicken Caesar Salad Prep","category":"lunch","calories":360,"prep_time":"20 min","description":"Classic Caesar made lighter with Greek yogurt dressing.","ingredients":["6 oz grilled chicken breast","3 cups chopped romaine","2 tbsp light Caesar dressing","1 tbsp parmesan","Whole wheat croutons"],"steps":["Grill or bake chicken breast","Let chicken cool and slice","Chop romaine lettuce","Divide lettuce and chicken into containers","Pack dressing, parmesan, and croutons separately","Combine when ready to eat"]},
        {"name":"Stuffed Sweet Potato","category":"lunch","calories":380,"prep_time":"40 min","description":"Baked sweet potato loaded with black beans and salsa.","ingredients":["2 medium sweet potatoes","1/2 cup black beans","2 tbsp salsa","2 tbsp Greek yogurt","1 green onion sliced"],"steps":["Preheat oven to 400F","Pierce sweet potatoes with a fork","Bake 35-40 min until soft","Cut open and fluff the insides","Top with beans, salsa, yogurt, and green onion","Wrap in foil for meal prep"]},
        # DINNER
        {"name":"Baked Lemon Herb Chicken","category":"dinner","calories":390,"prep_time":"30 min","description":"Juicy baked chicken thighs with roasted veggies.","ingredients":["4 chicken thighs (boneless skinless)","2 cups mixed vegetables","2 tbsp olive oil","2 cloves garlic","1 lemon","Fresh herbs (rosemary, thyme)"],"steps":["Preheat oven to 425F","Toss veggies with 1 tbsp olive oil on a sheet pan","Season chicken with herbs, garlic, lemon, salt, pepper","Place chicken on veggies","Bake 25-30 min until chicken reaches 165F","Divide into 4 containers"]},
        {"name":"Beef & Broccoli","category":"dinner","calories":400,"prep_time":"20 min","description":"Better-than-takeout with lean beef.","ingredients":["8 oz flank steak sliced thin","3 cups broccoli florets","2 tbsp soy sauce","1 tbsp oyster sauce","1 tsp cornstarch","1 clove garlic","Brown rice"],"steps":["Mix soy sauce, oyster sauce, and cornstarch for sauce","Stir fry sliced beef on high heat 3 min, set aside","Stir fry broccoli with garlic 4 min","Return beef to pan and add sauce","Cook 2 min until sauce thickens","Serve over brown rice"]},
        {"name":"Turkey Chili","category":"dinner","calories":350,"prep_time":"35 min","description":"Lean, hearty chili loaded with beans and spices.","ingredients":["1 lb ground turkey","1 can kidney beans","1 can diced tomatoes","1 onion diced","2 cloves garlic","2 tbsp chili powder","1 tsp cumin"],"steps":["Brown turkey and onion in a large pot","Add garlic and spices, cook 1 min","Add tomatoes and beans","Bring to a boil, then simmer 25 min","Season to taste","Makes 5-6 servings","Freezes perfectly for up to 3 months"]},
        {"name":"Baked Salmon with Asparagus","category":"dinner","calories":380,"prep_time":"20 min","description":"One-pan omega-3 powerhouse dinner.","ingredients":["4 salmon fillets","1 bunch asparagus trimmed","2 tbsp olive oil","2 cloves garlic minced","1 lemon","Salt and pepper"],"steps":["Preheat oven to 400F","Line a sheet pan with parchment","Arrange salmon and asparagus on pan","Drizzle with olive oil, garlic, lemon, salt, pepper","Bake 15-18 min until salmon flakes","Divide into 4 containers"]},
        {"name":"Chicken Fajita Bowls","category":"dinner","calories":410,"prep_time":"25 min","description":"Sizzling fajita flavors prepped for the week.","ingredients":["1 lb chicken breast","2 bell peppers sliced","1 onion sliced","2 tbsp fajita seasoning","1 cup brown rice","Lime wedges"],"steps":["Cook brown rice","Slice chicken into strips","Season chicken and veggies with fajita seasoning","Cook chicken in a hot skillet 6-7 min","Add peppers and onions, cook 5 min","Divide rice, chicken, and veggies into 4 containers","Add lime wedges"]},
        {"name":"Stuffed Zucchini Boats","category":"dinner","calories":320,"prep_time":"30 min","description":"Low-carb boats filled with seasoned ground turkey.","ingredients":["4 large zucchini","1 lb ground turkey","1/2 cup marinara sauce","1/4 cup mozzarella","1 tsp Italian seasoning","1 clove garlic"],"steps":["Preheat oven to 400F","Halve zucchini and scoop out centers","Brown turkey with garlic and Italian seasoning","Mix turkey with marinara","Fill zucchini halves with mixture","Top with mozzarella","Bake 20 min until cheese melts"]},
        {"name":"Shrimp & Cauliflower Grits","category":"dinner","calories":310,"prep_time":"20 min","description":"Southern comfort food made low-carb.","ingredients":["8 oz shrimp","3 cups riced cauliflower","2 tbsp butter","1/4 cup parmesan","1 clove garlic","Paprika and salt"],"steps":["Cook riced cauliflower in butter until tender (8 min)","Stir in parmesan for grits texture","Season shrimp with paprika and salt","Sear shrimp in a hot pan 2-3 min per side","Serve shrimp over cauliflower grits","Divide into containers"]},
        {"name":"One-Pot Chicken & Rice","category":"dinner","calories":400,"prep_time":"30 min","description":"Simple comfort meal — one pot, minimal cleanup.","ingredients":["4 chicken thighs","1 cup long grain rice","2 cups chicken broth","1 cup peas","1 tsp paprika","1 tsp garlic powder"],"steps":["Season chicken with paprika and garlic powder","Sear chicken in a pot 4 min per side, remove","Add rice and broth to pot, stir","Place chicken on top of rice","Cover and simmer 20 min","Add peas last 5 min","Fluff and divide into 4 containers"]},
        {"name":"Mediterranean Baked Fish","category":"dinner","calories":340,"prep_time":"25 min","description":"White fish baked with tomatoes, olives, and capers.","ingredients":["4 white fish fillets (tilapia/cod)","1 cup cherry tomatoes halved","2 tbsp kalamata olives","1 tbsp capers","2 tbsp olive oil","Fresh basil"],"steps":["Preheat oven to 400F","Place fish in a baking dish","Scatter tomatoes, olives, and capers around fish","Drizzle with olive oil, season with salt and pepper","Bake 18-20 min until fish flakes","Garnish with fresh basil"]},
        {"name":"Slow Cooker Pulled Chicken","category":"dinner","calories":360,"prep_time":"10 min (+ slow cook)","description":"Set it and forget it — tender shredded chicken.","ingredients":["2 lbs chicken breast","1 cup salsa","1 tbsp cumin","1 tsp garlic powder","1 tsp chili powder","Tortillas or rice for serving"],"steps":["Place chicken in slow cooker","Pour salsa over chicken","Add all spices","Cook on low 6-8 hours or high 3-4 hours","Shred with two forks","Use for tacos, bowls, salads, or wraps all week"]},
        {"name":"Eggplant Parmesan (Baked)","category":"dinner","calories":330,"prep_time":"35 min","description":"Baked not fried — lighter Italian classic.","ingredients":["1 large eggplant sliced","1 cup marinara sauce","1/2 cup mozzarella","1/4 cup parmesan","1/2 cup breadcrumbs","1 egg beaten"],"steps":["Preheat oven to 400F","Dip eggplant slices in egg then breadcrumbs","Lay on a baking sheet and bake 15 min, flip, bake 10 more","Layer in a dish: sauce, eggplant, cheese","Repeat layers","Bake 15 min until cheese bubbles","Cut into portions"]},
        {"name":"Honey Garlic Chicken Thighs","category":"dinner","calories":380,"prep_time":"25 min","description":"Sweet and savory glazed chicken.","ingredients":["6 chicken thighs boneless","3 tbsp honey","3 tbsp soy sauce","3 cloves garlic minced","1 tbsp olive oil","Steamed vegetables"],"steps":["Mix honey, soy sauce, and garlic for glaze","Heat olive oil in an oven-safe skillet","Sear chicken 4 min per side","Pour glaze over chicken","Bake at 400F for 15 min","Serve with steamed veggies","Divide into 4-6 containers"]},
        {"name":"Black Bean Veggie Burgers","category":"dinner","calories":300,"prep_time":"25 min","description":"Homemade plant-based patties — freezer friendly.","ingredients":["2 cans black beans drained","1/2 cup breadcrumbs","1 egg","1/4 cup diced onion","1 tsp cumin","1 tsp garlic powder","Lettuce buns or whole wheat buns"],"steps":["Mash black beans leaving some chunks","Mix in breadcrumbs, egg, onion, and spices","Form into 6 patties","Bake at 375F for 10 min per side","Or pan fry 4 min per side","Freeze extras between parchment paper"]},
        {"name":"Chicken Sausage & Veggie Sheet Pan","category":"dinner","calories":350,"prep_time":"25 min","description":"Everything on one pan — easy cooking, easy cleanup.","ingredients":["4 chicken sausage links sliced","2 cups Brussels sprouts halved","1 cup sweet potato cubed","1 tbsp olive oil","1 tsp Italian seasoning"],"steps":["Preheat oven to 425F","Toss sausage, Brussels sprouts, and sweet potato with oil and seasoning","Spread on a sheet pan in single layer","Bake 25 min, stirring halfway","Divide into 4 containers"]},
        {"name":"Thai Peanut Chicken","category":"dinner","calories":400,"prep_time":"20 min","description":"Creamy peanut sauce over chicken and veggies.","ingredients":["1 lb chicken breast cubed","2 tbsp peanut butter","1 tbsp soy sauce","1 tbsp lime juice","1 tsp sriracha","1 cup shredded cabbage","Brown rice"],"steps":["Mix peanut butter, soy sauce, lime juice, and sriracha for sauce","Cook chicken cubes in a skillet 6-7 min","Add sauce and toss to coat","Cook 2 more min","Serve over rice with shredded cabbage","Divide into 4 containers"]},
        {"name":"Lemon Garlic Shrimp Pasta","category":"dinner","calories":390,"prep_time":"20 min","description":"Light pasta with garlic shrimp and spinach.","ingredients":["8 oz whole wheat pasta","1 lb shrimp peeled","4 cloves garlic minced","2 cups spinach","2 tbsp olive oil","1 lemon","Red pepper flakes"],"steps":["Cook pasta according to package, reserve 1/2 cup pasta water","Saute garlic in olive oil 30 seconds","Add shrimp and cook 3 min per side","Add spinach and lemon juice","Toss with pasta and splash of pasta water","Season with red pepper flakes","Divide into 4 containers"]},
    ]

    for d in defaults:
        meal = Meal(
            name=d["name"], category=d["category"], calories=d["calories"],
            prep_time=d["prep_time"], description=d["description"],
            ingredients=json.dumps(d["ingredients"]),
            steps=json.dumps(d["steps"]),
            is_default=True, created_by=None,
        )
        db.session.add(meal)
    db.session.commit()
    print(f"Seeded {len(defaults)} default meals.")


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════

with app.app_context():
    db.create_all()
    seed_defaults()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
