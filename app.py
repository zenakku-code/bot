from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import json
import time
import os

app = Flask(__name__)

def create_driver():
    """Crea una instancia de Chrome con opciones para Render"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Configuración adicional para evitar detección
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        '''
    })
    
    return driver

def parse_price(price_text):
    """Extrae el precio numérico del texto"""
    try:
        # Elimina símbolos de moneda y comas
        price_clean = price_text.replace('$', '').replace(',', '').replace('.', '').strip()
        return float(price_clean)
    except:
        return 0

@app.route('/health', methods=['GET'])
def health():
    """Endpoint de salud para verificar que el servidor está funcionando"""
    return jsonify({"status": "ok", "message": "Facebook Marketplace Scraper API is running"}), 200

@app.route('/scrape', methods=['POST'])
def scrape_facebook_marketplace():
    """
    Endpoint principal para scrapear Facebook Marketplace
    
    Body JSON:
    {
        "search_term": "ps3",
        "cookies": "cookie_string_here" (opcional)
    }
    """
    driver = None
    
    try:
        # Obtener parámetros del request
        data = request.get_json()
        search_term = data.get('search_term', '')
        cookies_str = data.get('cookies', '')
        
        if not search_term:
            return jsonify({"error": "search_term is required"}), 400
        
        # Crear driver
        driver = create_driver()
        
        # Construir URL de búsqueda
        url = f"https://www.facebook.com/marketplace/search/?query={search_term}"
        
        # Navegar a Facebook Marketplace
        driver.get(url)
        
        # Si se proporcionan cookies, agregarlas
        if cookies_str:
            try:
                # Parsear cookies (formato: "name1=value1; name2=value2")
                cookie_pairs = cookies_str.split(';')
                for pair in cookie_pairs:
                    if '=' in pair:
                        name, value = pair.strip().split('=', 1)
                        driver.add_cookie({'name': name, 'value': value, 'domain': '.facebook.com'})
                
                # Recargar página con cookies
                driver.get(url)
            except Exception as e:
                print(f"Error adding cookies: {e}")
        
        # Esperar a que cargue el contenido
        time.sleep(5)
        
        # Intentar extraer productos
        products = []
        
        try:
            # Esperar a que aparezcan los elementos de productos
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Scroll para cargar más contenido
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(2)
            
            # Buscar elementos de productos (estos selectores pueden cambiar)
            # Intentar múltiples estrategias de extracción
            
            # Estrategia 1: Buscar por atributos de datos
            product_elements = driver.find_elements(By.CSS_SELECTOR, '[data-testid="marketplace-feed-item"]')
            
            if not product_elements:
                # Estrategia 2: Buscar por estructura de divs
                product_elements = driver.find_elements(By.CSS_SELECTOR, 'div[role="article"]')
            
            if not product_elements:
                # Estrategia 3: Buscar enlaces de marketplace
                product_elements = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/marketplace/item/"]')
            
            for element in product_elements[:20]:  # Limitar a 20 productos
                try:
                    # Extraer nombre del producto
                    name_elem = element.find_element(By.CSS_SELECTOR, 'span')
                    name = name_elem.text.strip()
                    
                    # Extraer precio
                    price_text = ""
                    try:
                        price_elem = element.find_element(By.XPATH, './/span[contains(text(), "$") or contains(text(), "ARS")]')
                        price_text = price_elem.text
                    except:
                        # Intentar otra estrategia para el precio
                        spans = element.find_elements(By.TAG_NAME, 'span')
                        for span in spans:
                            text = span.text
                            if '$' in text or 'ARS' in text:
                                price_text = text
                                break
                    
                    price = parse_price(price_text)
                    
                    # Solo agregar si tiene nombre y precio válidos
                    if name and len(name) > 3 and price > 0:
                        products.append({
                            "name": name,
                            "price": price
                        })
                
                except Exception as e:
                    continue
            
            # Si no se encontraron productos, intentar extraer del HTML completo
            if len(products) == 0:
                page_source = driver.page_source
                
                # Buscar patrones de precios en el HTML
                import re
                price_pattern = r'\$\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)'
                prices = re.findall(price_pattern, page_source)
                
                # Retornar información de debug si no hay productos
                return jsonify({
                    "success": False,
                    "message": "No products found. Facebook may be blocking the request.",
                    "products": [],
                    "debug": {
                        "url": url,
                        "prices_found": len(prices),
                        "page_title": driver.title,
                        "cookies_used": bool(cookies_str)
                    }
                }), 200
        
        except TimeoutException:
            return jsonify({
                "error": "Timeout waiting for page to load",
                "products": []
            }), 500
        
        # Cerrar driver
        driver.quit()
        
        return jsonify({
            "success": True,
            "search_term": search_term,
            "products": products,
            "count": len(products)
        }), 200
    
    except Exception as e:
        if driver:
            driver.quit()
        
        return jsonify({
            "error": str(e),
            "products": []
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)